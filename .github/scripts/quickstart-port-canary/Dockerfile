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

ARG PINOT_IMAGE=apachepinot/pinot@sha256:6ff4820a24f18adbd90eac465f501c55dec787d2ba4d582310b9384c7f8d1b5b
FROM ${PINOT_IMAGE} AS compiler
COPY QuickstartRunner.java PortRaceAgent.java /canary-build/
RUN set -eu; \
    set -- /opt/pinot/lib/*jar-with-dependencies.jar; \
    test "$#" -eq 1; test -f "$1"; \
    mkdir -p /canary-build/classes /canary-build/agent; \
    jar tf "$1" | grep -q '^org/apache/pinot/shaded/com/fasterxml/jackson/databind/JsonNode.class$'; \
    javap -public -cp "$1" org.apache.pinot.tools.admin.command.QuickstartRunner > /canary-build/original-api.txt; \
    javac -cp "$1" -d /canary-build/classes /canary-build/QuickstartRunner.java; \
    javap -public -cp "/canary-build/classes:$1" org.apache.pinot.tools.admin.command.QuickstartRunner > /canary-build/patched-api.txt; \
    cmp /canary-build/original-api.txt /canary-build/patched-api.txt; \
    javac -cp "$1" -d /canary-build/agent /canary-build/PortRaceAgent.java; \
    cd /canary-build/agent; jar xf "$1" org/objectweb/asm; \
    printf 'Premain-Class: canary.PortRaceAgent\n' > /canary-build/manifest; \
    jar cfm /canary-build/port-race-agent.jar /canary-build/manifest .

# Inherit the original entrypoint, classpath and all image/JVM environment settings.
FROM ${PINOT_IMAGE} AS baseline
COPY --from=compiler /canary-build/port-race-agent.jar /canary/port-race-agent.jar
COPY --from=compiler /canary-build/original-api.txt /canary-build/patched-api.txt /canary/

FROM baseline AS patched
COPY --from=compiler /canary-build/classes /canary/classes
RUN set -eu; set -- /opt/pinot/lib/*jar-with-dependencies.jar; \
    test "$#" -eq 1; test -f "$1"; \
    jar uf "$1" -C /canary/classes org/apache/pinot/tools/admin/command; \
    sha256sum "$1" /canary/port-race-agent.jar
