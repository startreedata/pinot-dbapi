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
FIX_COMMIT = "409f57823386bd0f7c8e4e3ee8d5ca14b4327c29"
FIX_BASE = "dd2c3cdfac918e18a20ef20cfd2a55eb868d2054"
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


def read_source(repository, revision, path):
    url = f"https://raw.githubusercontent.com/{repository}/{revision}/{path}"
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read(), url


def dimension_overlay(build, revision):
    assert re.fullmatch(r"[0-9a-f]{40}", FIX_COMMIT), "Candidate must be an immutable reviewed commit"
    files = []
    for path in ("pinot-core/src/main/java/org/apache/pinot/core/data/manager/offline/"
                 "DimensionTableDataManager.java",
                 "pinot-core/src/main/java/org/apache/pinot/core/data/manager/provider/"
                 "DefaultTableDataManagerProvider.java"):
        original, original_url = read_source("apache/pinot", revision, path)
        upstream_base, _ = read_source("apache/pinot", FIX_BASE, path)
        assert original == upstream_base, f"Candidate base differs from pinned image source: {path}"
        candidate, candidate_url = read_source("xiangfu0/pinot", FIX_COMMIT, path)
        assert candidate != original, f"Missing reviewed dimension fix: {path}"
        name = Path(path).name
        source = candidate.decode()
        compiled = source.replace("import com.google.common.",
                                  "import org.apache.pinot.shaded.com.google.common.")
        (build / (name + ".base")).write_bytes(original)
        (build / (name + ".candidate")).write_bytes(candidate)
        (build / name).write_text(compiled)
        (build / (name + ".patch")).write_text("".join(difflib.unified_diff(
            original.decode().splitlines(True), source.splitlines(True), "base/" + path, "candidate/" + path)))
        files.append({"path": path, "original_url": original_url, "candidate_url": candidate_url,
                      "original_sha256": hashlib.sha256(original).hexdigest(),
                      "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
                      "compiled_sha256": hashlib.sha256(compiled.encode()).hexdigest()})
    return {"commit": FIX_COMMIT, "base": FIX_BASE, "files": files}


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
    # The image's Maven shade step relocated Jackson in both the class and its API.
    # Compile with that existing namespace; retain the unshaded six-line source diff.
    original_import = "import com.fasterxml.jackson.databind.JsonNode;"
    shaded_import = "import org.apache.pinot.shaded.com.fasterxml.jackson.databind.JsonNode;"
    assert patched.count(original_import) == 1, "Unexpected Jackson source import"
    compiled_source = patched.replace(original_import, shaded_import)
    build = EVIDENCE / "build"
    build.mkdir()
    (build / "QuickstartRunner.base.java").write_bytes(source_bytes)
    (build / "QuickstartRunner.port-fix.java").write_text(patched)
    (build / "QuickstartRunner.java").write_text(compiled_source)
    (build / "QuickstartRunner.patch").write_text(diff)
    dimension_fix = dimension_overlay(build, revision)
    candidate_runner, _ = read_source("xiangfu0/pinot", FIX_COMMIT,
                                     "pinot-tools/src/main/java/org/apache/pinot/tools/admin/command/"
                                     "QuickstartRunner.java")
    assert candidate_runner == patched.encode(), "Canary port overlay differs from reviewed candidate"
    identity = {"image": IMAGE, "implementation_version": version.group(1),
                "source_commit": revision, "source_url": url,
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "patched_source_sha256": hashlib.sha256(patched.encode()).hexdigest(),
                "compiled_source_sha256": hashlib.sha256(compiled_source.encode()).hexdigest(),
                "distribution_import_relocation": {"from": original_import, "to": shaded_import},
                "dimension_scope_fix": dimension_fix}
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


def dimension_health(phase):
    samples = []
    deadline = time.monotonic() + 120
    while True:
        body = command(["curl", "--fail", "--silent", "--show-error", "--max-time", "10",
                        "http://localhost:9000/tables/dimBaseballTeams/externalview?tableType=OFFLINE"])
        view = json.loads(body).get("OFFLINE", {})
        samples.append({"time": time.time(), "view": view})
        (EVIDENCE / f"dimension-{phase}.json").write_text(json.dumps(samples, indent=2))
        healthy = bool(view) and all(
            len(states) == 3 and sorted(server.rsplit("_", 1)[-1] for server in states) ==
            ["7050", "7051", "7052"] and set(states.values()) == {"ONLINE"}
            for states in view.values())
        if healthy:
            return
        assert time.monotonic() < deadline, f"Dimension replicas did not become ONLINE: {view}"
        time.sleep(2)


def dimension_lookup():
    queries = {
        "false": ("select lookup('dimBaseballTeams', 'teamName', 'teamID', leftSubStr(teamID, 2)) AS teamName "
                  "from baseballStats where teamID LIKE 'SF%' limit 1"),
        "true": ("select /*+ joinOptions(join_strategy='lookup') */ d.teamName "
                 "from (select leftSubStr(teamID, 2) AS dimKey from baseballStats where teamID LIKE 'SF%') b "
                 "join dimBaseballTeams d on b.dimKey = d.teamID limit 1"),
    }
    (EVIDENCE / "dimension-lookup-queries.json").write_text(json.dumps(queries, indent=2))
    results = {}
    for engine, sql in queries.items():
        body = command(["curl", "--fail", "--silent", "--show-error", "--max-time", "30",
                        "-H", "Content-Type: application/json", "-d",
                        json.dumps({"sql": sql, "queryOptions": f"useMultistageEngine={engine}"}),
                        "http://localhost:8000/query/sql"])
        parsed = json.loads(body)
        results[engine] = parsed
        (EVIDENCE / "dimension-lookup.json").write_text(json.dumps(results, indent=2))
        assert not parsed.get("exceptions"), parsed
        assert parsed["resultTable"]["rows"] == [["San Francisco Giants"]], parsed


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
        file_logs = "\n".join(path.read_text(errors="replace")
                              for path in (EVIDENCE / "pinot-logs").glob("*.log"))
        primary = re.search(r"Caught exception while pre-serving queries,[\s\S]*?"
                            r"(?=\n\d{4}[-/]\d{2}[-/]\d{2}|\Z)", file_logs)
        assert primary, "Missing first pre-serve failure from Pinot file logs"
        primary = primary.group(0)
        assert "org.apache.pinot.query.service.server.QueryServer.start(" in primary, primary
        bind_errors = ("java.net.BindException: Address already in use",
                       "io.grpc.netty.shaded.io.netty.channel.unix.Errors$NativeIoException: "
                       "bind(..) failed with error(-98): Address already in use")
        assert any(error in primary for error in bind_errors), primary
        assert re.search(rf"Failed to bind to address[^\n]*:{agent['port']}\b", primary), primary
        (EVIDENCE / "mse-bind-failure.txt").write_text(primary)
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
        file_logs = "\n".join(path.read_text(errors="replace")
                              for path in (EVIDENCE / "pinot-logs").glob("*.log"))
        blocks = re.split(r"(?m)(?=^\d{4}[-/]\d{2}[-/]\d{2})", file_logs)
        assert not any("dimBaseballTeams" in block and any(error in block for error in
                       ("Unable to create index directory", "is not a directory",
                        "Maximum permit count exceeded")) for block in blocks), \
            "Dimension manager directory or permit failure remains"
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
        # Keep WARN stacks in the existing file appender; the console filters them out.
        (EVIDENCE / "pinot-logs").mkdir()
        command(["docker", "create", "--name", CONTAINER, "--publish", "9000:9000",
                 "--publish", "8000:8000", "--volume", f"{EVIDENCE}:/evidence",
                 "--env", "LOG_ROOT=/evidence/pinot-logs", "--env", "PINOT_COMPONENT=all",
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
            dimension_health("before-integration")
            env["PYTEST_ADDOPTS"] = (env.get("PYTEST_ADDOPTS", "")
                                     + f" --junitxml={EVIDENCE / 'integration.xml'}").strip()
            command(["make", "test-integration"], "integration.log", env)
            dimension_lookup()
            dimension_health("after-integration")
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
