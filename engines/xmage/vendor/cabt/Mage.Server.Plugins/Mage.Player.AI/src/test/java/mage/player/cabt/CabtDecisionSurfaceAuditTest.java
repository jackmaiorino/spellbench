package mage.player.cabt;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class CabtDecisionSurfaceAuditTest {

    @Test
    void auditContainsPlayerPromptMethods() {
        String[] required = {
                "priority(Game)",
                "chooseTarget(Outcome, Target, Ability, Game)",
                "choose(Outcome, Choice, Game)",
                "chooseUse(Outcome, String, Ability, Game)",
                "chooseMode(Modes, Ability, Game)",
                "chooseTriggeredAbility(List<TriggeredAbility>, Game)",
                "chooseReplacementEffect(Map<String, String>, Map<String, MageObject>, Game)",
                "playMana(Ability, ManaCost, String, Game)",
                "selectAttackers(Game, UUID)",
                "selectBlockers(Ability, Game, UUID)",
                "chooseMulligan(Game)",
        };
        for (String name : required) {
            CabtDecisionSurface entry = findByName(name);
            assertThat(entry.getSource())
                    .as("source of %s", name)
                    .isEqualTo(CabtDecisionSurfaceSource.PLAYER_INTERFACE);
        }
    }

    @Test
    void auditSeparatesPriorityActionsFromPromptMethods() {
        assertThat(findByName("priority(Game)").getSource())
                .isEqualTo(CabtDecisionSurfaceSource.PLAYER_INTERFACE);
        assertThat(findByName("getPlayable(Game, boolean)").getSource())
                .isEqualTo(CabtDecisionSurfaceSource.PLAYABLE_OBJECTS);
        assertThat(findByName("getPlayableObjects(Game, Zone)").getSource())
                .isEqualTo(CabtDecisionSurfaceSource.PLAYABLE_OBJECTS);
    }

    @Test
    void auditContainsClientCallbackReferences() {
        String[] required = {
                "GameSessionPlayer.chooseChoice",
                "GameSessionPlayer.playMana",
                "GameSessionPlayer.getAmount",
                "GameSessionPlayer.getMultiAmount",
                "GameSessionPlayer.prepareGameView.canPlayObjects",
        };
        for (String name : required) {
            CabtDecisionSurface entry = findByName(name);
            assertThat(entry.getSource())
                    .as("source of %s", name)
                    .isEqualTo(CabtDecisionSurfaceSource.CLIENT_CALLBACK);
        }
    }

    @Test
    void auditReflectsCurrentBridgeStatus() {
        assertThat(findByName("priority(Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        // surfaced by Task 7's target prompts
        assertThat(findByName("chooseTarget(Outcome, Target, Ability, Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        assertThat(findByName("choose(Outcome, Target, Ability, Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        // surfaced by Tasks 8-10's generic/mode/number prompts
        assertThat(findByName("chooseMode(Modes, Ability, Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        assertThat(findByName("chooseUse(Outcome, String, Ability, Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        assertThat(findByName("announceX(int, int, String, Game, Ability, boolean)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        assertThat(findByName("chooseTriggeredAbility(List<TriggeredAbility>, Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        assertThat(findByName("chooseReplacementEffect(Map<String, String>, Map<String, MageObject>, Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        assertThat(findByName("playMana(Ability, ManaCost, String, Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        assertThat(findByName("selectAttackers(Game, UUID)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        assertThat(findByName("selectBlockers(Ability, Game, UUID)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        assertThat(findByName("chooseMulligan(Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        // surfaced by Task 23: the map overload delegates to the four-argument choose
        assertThat(findByName("choose(Outcome, Target, Ability, Game, Map<String, Serializable>)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.SURFACED);
        // not yet surfaced: fails closed with CabtUnhandledDecisionException
        assertThat(findByName("chooseTargetAmount(Outcome, TargetAmount, Ability, Game)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.FAIL_CLOSED);
        assertThat(findByName("getPlayableObjects(Game, Zone)").getStatus())
                .isEqualTo(CabtDecisionSurfaceStatus.REFERENCE_ONLY);
        assertThat(findByName("Arena/17Lands replay comparison").getSource())
                .isEqualTo(CabtDecisionSurfaceSource.ARENA_LOG_COMPARISON);
    }

    @Test
    void entriesListIsUnmodifiable() {
        List<CabtDecisionSurface> entries = CabtDecisionSurfaceAudit.entries();
        try {
            entries.add(null);
            throw new AssertionError("entries() must be unmodifiable");
        } catch (UnsupportedOperationException expected) {
            // the audit list must not be mutable by callers
        }
    }

    @Test
    void noUnknownPlayableActionType() {
        // an unrecognized action must fail audit/tests, not fall back to a
        // catch-all enum constant
        Class<?>[] projectEnums = {
                MagicOptionType.class,
                MagicSelectType.class,
                CabtDecisionSurfaceSource.class,
                CabtDecisionSurfaceStatus.class,
        };
        for (Class<?> enumClass : projectEnums) {
            for (Object constant : enumClass.getEnumConstants()) {
                assertThat(((Enum<?>) constant).name())
                        .as("enum constant of %s", enumClass.getSimpleName())
                        .isNotEqualTo("UNKNOWN_PLAYABLE");
            }
        }
    }

    @Test
    void docsExplain17LandsIsTelemetryNotLegalDecisionSource() throws IOException {
        Path docs = resolveDocs();
        String content = new String(Files.readAllBytes(docs), StandardCharsets.UTF_8);
        assertThat(content)
                .contains("17Lands replay data is telemetry, not a legal-action enumerator.");
    }

    private static Path resolveDocs() {
        // surefire runs with the module directory as user.dir; fall back to
        // the repo-root-relative path for IDE runs
        Path moduleRelative = Paths.get("docs", "cabt-decision-surface.md");
        if (Files.exists(moduleRelative)) {
            return moduleRelative;
        }
        return Paths.get("Mage.Server.Plugins", "Mage.Player.AI",
                "docs", "cabt-decision-surface.md");
    }

    private static CabtDecisionSurface findByName(String name) {
        for (CabtDecisionSurface entry : CabtDecisionSurfaceAudit.entries()) {
            if (entry.getName().equals(name)) {
                return entry;
            }
        }
        throw new AssertionError("audit is missing decision surface: " + name);
    }
}
