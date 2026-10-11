#!/usr/bin/env python3
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

"""Temporary issue 242 mechanism canary; no release image is built or published."""

import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET


IMAGE = "apachepinot/pinot@sha256:6ff4820a24f18adbd90eac465f501c55dec787d2ba4d582310b9384c7f8d1b5b"
SCRIPT = Path(__file__).resolve().parent
EVIDENCE = Path("quickstart-port-canary").resolve()
CONTAINER = "pinot-port-canary"
TABLES = ("airlineStats", "baseballStats", "dimBaseballTeams",
          "githubComplexTypeEvents", "githubEvents", "starbucksStores")


def command(args, output=None, env=None):
    if output is None:
        return subprocess.check_output(args, text=True, env=env)
    with open(EVIDENCE / output, "w") as log:
        process = subprocess.Popen(args, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, env=env)
        for line in process.stdout:
            print(line, end="", flush=True)
            log.write(line)
        assert process.wait() == 0, f"Command failed: {args}; see {output}"


def source_overlay(source):
    additions = (
        ("  private static final int DEFAULT_BROKER_GRPC_PORT = 8010;",
         "  private static final int DEFAULT_BROKER_MULTI_STAGE_RUNNER_PORT = 8030;"),
        ("  private static final int DEFAULT_SERVER_GRPC_PORT = 7100;",
         "  private static final int DEFAULT_SERVER_MULTI_STAGE_SERVER_PORT = 7200;\n"
         "  private static final int DEFAULT_SERVER_MULTI_STAGE_RUNNER_PORT = 7300;"),
        ("          .setGrpcPort(DEFAULT_BROKER_GRPC_PORT + i)",
         "          .setBrokerMultiStageRunnerPort(DEFAULT_BROKER_MULTI_STAGE_RUNNER_PORT + i)"),
        ("          .setGrpcPort(DEFAULT_SERVER_GRPC_PORT + i)",
         "          .setMultiStageServerPort(DEFAULT_SERVER_MULTI_STAGE_SERVER_PORT + i)\n"
         "          .setMultiStageRunnerPort(DEFAULT_SERVER_MULTI_STAGE_RUNNER_PORT + i)"),
    )
    patched = source
    for anchor, addition in additions:
        assert patched.count(anchor) == 1, f"Unexpected image source: {anchor}"
        assert addition not in patched, "Pinned image already has candidate defaults"
        patched = patched.replace(anchor, anchor + "\n" + addition)
    diff = list(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                   "QuickstartRunner.base.java", "QuickstartRunner.java"))
    assert sum(line.startswith("+") and not line.startswith("+++") for line in diff) == 6
    assert not any(line.startswith("-") and not line.startswith("---") for line in diff)
    return patched, "".join(diff)


def prepare(mode):
    command(["docker", "pull", IMAGE], "pull.log")
    original = json.loads(command(["docker", "image", "inspect", IMAGE]))[0]
    (EVIDENCE / "original-image.json").write_text(json.dumps(original, indent=2))
    # Read the actual pinned image's build identity. A temporal source snapshot is insufficient.
    manifest = command(["docker", "run", "--rm", "--entrypoint", "sh", IMAGE, "-c",
                        'set -eu; set -- /opt/pinot/lib/*jar-with-dependencies.jar; '
                        'test "$#" -eq 1; test -f "$1"; sha256sum "$1"; '
                        'mkdir -p /tmp/canary-manifest; cd /tmp/canary-manifest; '
                        'jar xf "$1" META-INF/MANIFEST.MF; cat META-INF/MANIFEST.MF'])
    (EVIDENCE / "image-fatjar-manifest.txt").write_text(manifest)
    unfolded = manifest.replace("\r\n", "\n").replace("\n ", "")
    version = re.search(r"^Implementation-Version: (.+)$", unfolded, re.M)
    assert version, "Image does not expose an authoritative source build identity"
    revision = re.search(r"-([0-9a-f]{40})$", version.group(1))
    assert revision, "Image Implementation-Version has no exact commit; cannot safely overlay"
    revision = revision.group(1)
    url = (f"https://raw.githubusercontent.com/apache/pinot/{revision}/pinot-tools/"
           "src/main/java/org/apache/pinot/tools/admin/command/QuickstartRunner.java")
    with urllib.request.urlopen(url, timeout=30) as response:
        source_bytes = response.read()
    source = source_bytes.decode()
    patched, diff = source_overlay(source)
    build = EVIDENCE / "build"
    build.mkdir()
    (build / "QuickstartRunner.base.java").write_bytes(source_bytes)
    (build / "QuickstartRunner.java").write_text(patched)
    (build / "QuickstartRunner.patch").write_text(diff)
    identity = {"image": IMAGE, "implementation_version": version.group(1),
                "source_commit": revision, "source_url": url,
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "patched_source_sha256": hashlib.sha256(patched.encode()).hexdigest()}
    (EVIDENCE / "identity.json").write_text(json.dumps(identity, indent=2))
    print(json.dumps(identity, indent=2), flush=True)
    shutil.copy(SCRIPT / "PortRaceAgent.java", build)
    tag = f"pinot-port-canary:{mode}"
    command(["docker", "build", "--target", mode, "--build-arg", f"PINOT_IMAGE={IMAGE}",
             "--tag", tag, "--file", str(SCRIPT / "Dockerfile"), str(build)], "build.log")
    derived = json.loads(command(["docker", "image", "inspect", tag]))[0]
    (EVIDENCE / "derived-image.json").write_text(json.dumps(derived, indent=2))
    for key in ("Entrypoint", "Cmd", "Env", "WorkingDir"):
        assert original["Config"][key] == derived["Config"][key], f"Changed image {key}"
    launcher = 'set -eu; sha256sum bin/pinot-admin.sh; cat bin/pinot-admin.sh'
    before = command(["docker", "run", "--rm", "--entrypoint", "sh", IMAGE, "-c", launcher])
    after = command(["docker", "run", "--rm", "--entrypoint", "sh", tag, "-c", launcher])
    assert before == after, "Overlay changed launcher/classpath"
    (EVIDENCE / "launcher.txt").write_text(before)
    return tag, original


def has_190(body):
    try:
        parsed = json.loads(body)
    except ValueError:
        return False
    return isinstance(parsed, dict) and any(
        isinstance(error, dict) and error.get("errorCode") == 190
        for error in parsed.get("exceptions") or [])


def probe(stop):
    with open(EVIDENCE / "host-curl.jsonl", "w") as stream:
        while not stop.is_set():
            result = subprocess.run(
                ["curl", "--silent", "--show-error", "--max-time", "2", "-w", "\n%{http_code}",
                 "-H", "Content-Type: application/json", "-d",
                 json.dumps({"sql": "select count(*) from airlineStats limit 1"}),
                 "http://localhost:8000/query/sql"], text=True, capture_output=True)
            body, _, status = result.stdout.rpartition("\n")
            row = {"time": time.time(), "curl_exit": result.returncode,
                   "http_status": status, "body": body, "stderr": result.stderr}
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            if has_190(body):
                (EVIDENCE / "observed-190").touch()
            # Retain one final empty response after a child exit before ending the monitor.
            running = command(["docker", "inspect", "--format", "{{.State.Running}}", CONTAINER]).strip()
            if (running == "false" and (EVIDENCE / "started").exists()
                    and not body and result.returncode != 0):
                break
            stop.wait(1)


def retain():
    for args, name in ((["docker", "inspect", CONTAINER], "container.json"),
                       (["docker", "logs", "--timestamps", CONTAINER], "container.log"),
                       (["docker", "ps", "-a", "--no-trunc"], "containers.txt")):
        result = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (EVIDENCE / name).write_text(result.stdout)


def assert_evidence(mode):
    state = json.loads((EVIDENCE / "container.json").read_text())[0]["State"]
    agent = dict(line.split("=", 1) for line in (EVIDENCE / "agent.properties").read_text().splitlines())
    assert agent["transformed"] == "true", "Agent did not transform the actual configuration class"
    assert not state["OOMKilled"], "OOM is a different failure mechanism"
    logs = (EVIDENCE / "container.log").read_text()
    samples = [json.loads(line) for line in (EVIDENCE / "host-curl.jsonl").read_text().splitlines()]
    assert "PORT_CANARY instrumented" in logs
    if mode == "baseline":
        assert agent["stolen"] == "1"
        assert not state["Running"] and state["ExitCode"] == 255, state
        assert "java.net.BindException: Address already in use" in logs
        assert "Starting a Pinot [SERVER]" in logs
        assert "PORT_CANARY host observed 190" in logs
        ports = [json.loads(line) for line in (EVIDENCE / "ports.jsonl").read_text().splitlines()]
        servers = [row for row in ports if row["role"] == "SERVER"]
        assert len(servers) == 1 and servers[0]["netty"] == 7050
        assert servers[0]["plan"] == int(agent["port"]), "Fault did not target the first server MSE port"
        seen = next(index for index, row in enumerate(samples) if has_190(row["body"]))
        assert any(not row["body"] and row["curl_exit"] != 0 for row in samples[seen + 1:]), \
            "Expected broker 190 followed by empty failed curl"
    else:
        assert agent["stolen"] == "0", "Patched defaults still allocated an unreserved server port"
        assert state["Running"] and state["ExitCode"] == 0, state
        assert logs.count("Started Pinot [SERVER] instance") == 3
        ports = [json.loads(line) for line in (EVIDENCE / "ports.jsonl").read_text().splitlines()]
        servers = [row for row in ports if row["role"] == "SERVER"]
        assert [(row["netty"], row["plan"], row["mailbox"]) for row in servers] == \
            [(7050 + i, 7200 + i, 7300 + i) for i in range(3)]
        assert [row["mailbox"] for row in ports if row["role"] == "BROKER"] == [8030]
        counts = {}
        for table in TABLES:
            body = command(["curl", "--fail", "--silent", "--show-error", "--max-time", "10",
                            "-H", "Content-Type: application/json", "-d",
                            json.dumps({"sql": f"select count(*) from {table} limit 1"}),
                            "http://localhost:8000/query/sql"])
            parsed = json.loads(body)
            assert not parsed.get("exceptions"), parsed
            counts[table] = parsed["resultTable"]["rows"][0][0]
            assert isinstance(counts[table], int) and counts[table] > 0, parsed
        (EVIDENCE / "six-table-counts.json").write_text(json.dumps(counts, indent=2))
        suites = ET.parse(EVIDENCE / "integration.xml").getroot().iter("testsuite")
        totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
        for suite in suites:
            for key in totals:
                totals[key] += int(suite.get(key, 0))
        assert totals == {"tests": 17, "failures": 0, "errors": 0, "skipped": 0}, totals
    result = {"mode": mode, "assertions": "PASS", "historical_attribution": "unproven",
              "published_or_deployed_fix": False, "container_state_before_cleanup": state,
              "agent": agent}
    (EVIDENCE / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)


def main():
    mode = sys.argv[1]
    assert mode in ("baseline", "patched")
    EVIDENCE.mkdir()
    stop = threading.Event()
    monitor = None
    events = None
    try:
        tag, original = prepare(mode)
        existing = next((item.split("=", 1)[1] for item in original["Config"]["Env"]
                         if item.startswith("JAVA_TOOL_OPTIONS=")), "")
        tool_options = (existing + " -javaagent:/canary/port-race-agent.jar=/evidence").strip()
        command(["docker", "create", "--name", CONTAINER, "--publish", "9000:9000",
                 "--publish", "8000:8000", "--volume", f"{EVIDENCE}:/evidence",
                 "--env", f"JAVA_TOOL_OPTIONS={tool_options}", tag, "QuickStart", "-type", "MULTI_STAGE"])
        event_log = open(EVIDENCE / "docker-events.jsonl", "w")
        events = subprocess.Popen(["docker", "events", "--filter", f"container={CONTAINER}",
                                   "--format", "{{json .}}"], stdout=event_log, stderr=subprocess.STDOUT)
        command(["docker", "start", CONTAINER])
        (EVIDENCE / "started").touch()
        monitor = threading.Thread(target=probe, args=(stop,), daemon=True)
        monitor.start()
        if mode == "baseline":
            deadline = time.monotonic() + 240
            while command(["docker", "inspect", "--format", "{{.State.Running}}", CONTAINER]).strip() == "true":
                assert time.monotonic() < deadline, "Expected child failure did not occur within 240 seconds"
                time.sleep(1)
            monitor.join(timeout=5)
        else:
            env = dict(os.environ, CONTROLLER_PORT_FORWARD="9000", BROKER_PORT_FORWARD="8000")
            command(["bash", ".github/scripts/setup_python_test_env.sh"], "setup.log", env)
            env["PYTEST_ADDOPTS"] = (env.get("PYTEST_ADDOPTS", "")
                                     + f" --junitxml={EVIDENCE / 'integration.xml'}").strip()
            command(["make", "test-integration"], "integration.log", env)
        stop.set()
        monitor.join(timeout=5)
        assert not monitor.is_alive(), "Host probe did not finish"
        retain()
        assert_evidence(mode)
    finally:
        stop.set()
        if monitor:
            monitor.join(timeout=5)
        if events:
            events.terminate()
            events.wait(timeout=5)
        retain()
        subprocess.run(["docker", "rm", "--force", CONTAINER], check=False)


if __name__ == "__main__":
    main()
