package mage.player.spellbench.x1;

import mage.player.spellbench.Secrets;
import mage.player.spellbench.ids.ObjectIds;

import java.io.PrintStream;

/**
 * Checks the secret, object-id and stream-seed derivations against the test vectors of protocol v2 Section 16
 * (run_secret = bytes 0x00..0x1f).
 */
final class SelfTest {

    private SelfTest() {
    }

    static boolean run(PrintStream out) {
        byte[] run = DeterminismCheck.runSecretVector();
        byte[] g0 = Secrets.gameSecret(run, 0);
        ObjectIds ids = new ObjectIds(g0);
        String[][] checks = {
                {"commitment", DeterminismCheck.hex(Secrets.sha256(run)),
                        "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd"},
                {"game_secret(0)", DeterminismCheck.hex(g0),
                        "7648831b4ae4148770e13149d5ebbe1c4991168413d4b38e49292cfc5538980e"},
                {"game_secret(1)", DeterminismCheck.hex(Secrets.gameSecret(run, 1)),
                        "952ea875cce08bf7706f87a89ae6a4e318a1bc4b46d6b506f8bb8505c518238e"},
                {"id_key(0)", ids.idKeyHex(),
                        "842e5229d41477f389ae25e2b8196afb5bfa8c6bd9b95d7bd3703031c88e22e6"},
                {"object id p0:card-17:z2", ids.visible("p0", "card-17:z2"), "o-0a3647243d16bf78"},
                {"object id p1:card-17:z2", ids.visible("p1", "card-17:z2"), "o-e5e4b7ed2a0730e4"},
                {"object id p0:card-17:z2:look:0", ids.look("p0", "card-17:z2", 0), "o-794a5cb152c9620f"},
                {"object id p0:card-17:z2:look:1", ids.look("p0", "card-17:z2", 1), "o-e18a35822cc60e1c"},
                {"stream seed p1:library_shuffle:0",
                        DeterminismCheck.first8(Secrets.streamSeed(g0, "p1", "library_shuffle", 0)), "8a28fd4db75719b1"},
        };
        boolean ok = true;
        for (String[] c : checks) {
            boolean pass = c[1].equals(c[2]);
            ok &= pass;
            out.println((pass ? "PASS " : "FAIL ") + c[0] + " = " + c[1] + (pass ? "" : " (want " + c[2] + ")"));
        }
        out.println(ok ? "selftest: all Section 16 vectors match" : "selftest: MISMATCH");
        return ok;
    }
}
