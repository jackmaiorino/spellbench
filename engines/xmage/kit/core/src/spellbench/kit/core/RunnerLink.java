package spellbench.kit.core;

import java.io.BufferedReader;
import java.io.File;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.TimeUnit;

/**
 * The front's link to its runner process (design Section 2.1). One request at a time; every request carries a
 * sequence number, and a reply whose number is not the pending one is discarded (late results never answer a later
 * request). A request that has no reply by its deadline plus the grace period ends the runner: it is destroyed
 * forcibly, its exit is confirmed (Process.destroyForcibly may return before the process ends), and the next request
 * starts a fresh runner, which boots and receives the game again. The runner's stderr goes to a log file, never to
 * the front's stdout.
 */
public final class RunnerLink {

    /** No reply in time: the runner was killed; the caller answers by fallback (tagged cap). */
    public static final class Timeout extends Exception {
        private static final long serialVersionUID = 1L;
        public final long waitedMs;
        public final boolean exitConfirmed;

        Timeout(long waitedMs, boolean exitConfirmed) {
            super("runner timeout after " + waitedMs + " ms");
            this.waitedMs = waitedMs;
            this.exitConfirmed = exitConfirmed;
        }
    }

    private final List<String> command;
    private final File workDir;
    private final File stderrLog;
    private Process process;
    private Writer toRunner;
    private BlockingQueue<String> replies;
    private Thread reader;
    private long seq;
    private Map<String, Object> gameMessage;
    /** Measurements for the evidence (E3, E8). */
    public long restarts;
    public long kills;
    public long lastBootMs;
    public long lastRestartMs;
    public long lateDiscarded;
    public final List<Long> killToExitMs = new ArrayList<>();

    public RunnerLink(List<String> command, File workDir, File stderrLog) {
        this.command = new ArrayList<>(command);
        this.workDir = workDir;
        this.stderrLog = stderrLog;
    }

    public boolean alive() {
        return process != null && process.isAlive();
    }

    /** The game message every fresh runner receives after its boot. */
    public void setGame(Map<String, Object> game) {
        this.gameMessage = game;
    }

    private void start() throws IOException, Timeout {
        long t0 = System.nanoTime();
        ProcessBuilder pb = new ProcessBuilder(command);
        pb.directory(workDir);
        pb.redirectError(ProcessBuilder.Redirect.appendTo(stderrLog));
        process = pb.start();
        toRunner = new OutputStreamWriter(process.getOutputStream(), StandardCharsets.UTF_8);
        final BlockingQueue<String> queue = new ArrayBlockingQueue<>(64);
        replies = queue;
        final Process p = process;
        reader = new Thread(() -> {
            try (BufferedReader in = new BufferedReader(new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = in.readLine()) != null) {
                    queue.offer(line);
                }
            } catch (IOException ignored) {
                // the runner ended
            }
        }, "kit-runner-reader");
        reader.setDaemon(true);
        reader.start();
        Map<String, Object> boot = call(Json.map("op", "boot"), 600_000, 10_000);
        lastBootMs = Json.num(boot, "boot_ms", -1);
        if (gameMessage != null) {
            call(gameMessage, 600_000, 10_000);
        }
        lastRestartMs = (System.nanoTime() - t0) / 1_000_000;
    }

    /** Sends one request and waits for its reply until {@code deadlineMs} + {@code graceMs}. */
    public Map<String, Object> call(Map<String, Object> request, long deadlineMs, long graceMs) throws IOException, Timeout {
        if (!alive()) {
            if (process != null) {
                restarts++;
            }
            start();
        }
        long mySeq = ++seq;
        request.put("seq", mySeq);
        toRunner.write(Json.canonical(request));
        toRunner.write('\n');
        toRunner.flush();
        long until = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(deadlineMs + graceMs);
        while (true) {
            long left = until - System.nanoTime();
            String line;
            try {
                line = left <= 0 ? null : replies.poll(left, TimeUnit.NANOSECONDS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                line = null;
            }
            if (line == null) {
                boolean confirmed = kill();
                throw new Timeout(deadlineMs + graceMs, confirmed);
            }
            Map<String, Object> reply;
            try {
                reply = Json.parseObject(line);
            } catch (RuntimeException e) {
                continue; // not a reply line
            }
            if (Json.num(reply, "seq", -1) != mySeq) {
                lateDiscarded++;
                continue; // a late result of an earlier request: never answers this one
            }
            return reply;
        }
    }

    /** Destroys the runner and confirms its exit; true when the process is gone. */
    public boolean kill() {
        if (process == null) {
            return true;
        }
        kills++;
        long t0 = System.nanoTime();
        process.destroyForcibly();
        boolean exited;
        try {
            exited = process.waitFor(30, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            exited = !process.isAlive();
        }
        killToExitMs.add((System.nanoTime() - t0) / 1_000_000);
        replies = new ArrayBlockingQueue<>(64); // nothing the dead runner wrote can answer a later request
        return exited;
    }

    public void close() {
        if (process != null) {
            try {
                toRunner.close();
            } catch (IOException ignored) {
                // closing stdin ends the runner
            }
            try {
                if (!process.waitFor(5, TimeUnit.SECONDS)) {
                    process.destroyForcibly();
                    process.waitFor(10, TimeUnit.SECONDS);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }
}
