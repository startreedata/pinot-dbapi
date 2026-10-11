/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements. See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership. The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License. You may obtain a copy of the License at
 * http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied. See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */
package canary;

import java.lang.instrument.ClassFileTransformer;
import java.lang.instrument.Instrumentation;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.ProtectionDomain;
import java.util.Map;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.Opcodes;

/** Temporary deterministic allocation-to-bind fault; never part of a published Pinot image. */
public final class PortRaceAgent {
  private static final String TARGET = "org/apache/pinot/tools/utils/PinotConfigUtils";
  private static Path directory;
  private static ServerSocket competitor;
  private static boolean transformed;

  public static void premain(String arguments, Instrumentation instrumentation) throws Exception {
    directory = Path.of(arguments);
    state();
    instrumentation.addTransformer(new ClassFileTransformer() {
      @Override
      public byte[] transform(ClassLoader loader, String name, Class<?> redefining,
          ProtectionDomain domain, byte[] bytes) {
        if (!TARGET.equals(name)) {
          return null;
        }
        ClassWriter writer = new ClassWriter(0);
        int[] hooks = new int[3];
        new ClassReader(bytes).accept(new ClassVisitor(Opcodes.ASM9, writer) {
          @Override
          public MethodVisitor visitMethod(int access, String method, String descriptor,
              String signature, String[] exceptions) {
            MethodVisitor visitor = super.visitMethod(access, method, descriptor, signature, exceptions);
            return new MethodVisitor(Opcodes.ASM9, visitor) {
              @Override
              public void visitInsn(int opcode) {
                if (method.equals("getAvailablePort") && descriptor.equals("()I")
                    && opcode == Opcodes.IRETURN) {
                  hooks[0]++;
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "canary/PortRaceAgent", "steal", "(I)I", false);
                } else if ((method.equals("generateServerConf") || method.equals("generateBrokerConf"))
                    && opcode == Opcodes.ARETURN) {
                  hooks[method.equals("generateServerConf") ? 1 : 2]++;
                  super.visitMethodInsn(Opcodes.INVOKESTATIC, "canary/PortRaceAgent",
                      method.equals("generateServerConf") ? "server" : "broker",
                      "(Ljava/util/Map;)Ljava/util/Map;", false);
                }
                super.visitInsn(opcode);
              }
            };
          }
        }, 0);
        if (hooks[0] != 1 || hooks[1] != 1 || hooks[2] != 1) {
          throw new IllegalStateException("Unexpected PinotConfigUtils bytecode hooks");
        }
        transformed = true;
        state();
        System.err.println("PORT_CANARY instrumented " + domain.getCodeSource().getLocation());
        return writer.toByteArray();
      }
    });
  }

  public static synchronized int steal(int port) {
    boolean server = false;
    for (StackTraceElement frame : Thread.currentThread().getStackTrace()) {
      if (frame.getClassName().equals(TARGET.replace('/', '.'))
          && frame.getMethodName().equals("generateServerConf")) {
        server = true;
      }
    }
    if (!server || competitor != null) {
      return port;
    }
    try {
      competitor = new ServerSocket();
      competitor.setReuseAddress(false);
      competitor.bind(new InetSocketAddress(port));
      state();
      System.err.println("PORT_CANARY stole first SERVER MSE port " + port);
      long deadline = System.nanoTime() + 45_000_000_000L;
      while (!Files.exists(directory.resolve("observed-190")) && System.nanoTime() < deadline) {
        Thread.sleep(100);
      }
      if (!Files.exists(directory.resolve("observed-190"))) {
        throw new IllegalStateException("Host did not observe broker error 190 within 45 seconds");
      }
      System.err.println("PORT_CANARY host observed 190; retaining competitor through real gRPC bind");
      return port;
    } catch (Exception exception) {
      throw new IllegalStateException("Port race injection failed", exception);
    }
  }

  public static Map<String, Object> server(Map<String, Object> config) {
    record("SERVER", config);
    return config;
  }

  public static Map<String, Object> broker(Map<String, Object> config) {
    record("BROKER", config);
    return config;
  }

  private static synchronized void record(String role, Map<String, Object> config) {
    String row = "{\"role\":\"" + role + "\",\"netty\":" + config.get("pinot.server.netty.port")
        + ",\"plan\":" + config.get("pinot.query.server.port")
        + ",\"mailbox\":" + config.get("pinot.query.runner.port") + "}\n";
    try {
      Files.writeString(directory.resolve("ports.jsonl"), row, StandardCharsets.UTF_8,
          StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    } catch (Exception exception) {
      throw new IllegalStateException("Cannot retain generated port evidence", exception);
    }
  }

  private static void state() {
    try {
      Files.writeString(directory.resolve("agent.properties"), "transformed=" + transformed
          + "\nstolen=" + (competitor != null && competitor.isBound() ? 1 : 0) + "\nport="
          + (competitor != null && competitor.isBound() ? competitor.getLocalPort() : 0) + "\n");
    } catch (Exception exception) {
      throw new IllegalStateException("Cannot retain agent state", exception);
    }
  }
}
