package mage.player.cabt;

import mage.cards.Card;
import mage.cards.CardSetInfo;
import mage.cards.basiclands.Forest;
import mage.cards.decks.Deck;
import mage.cards.g.GrizzlyBears;
import mage.constants.PhaseStep;
import mage.constants.RangeOfInfluence;
import mage.constants.Rarity;
import mage.game.GameOptions;
import mage.game.PutToBattlefieldInfo;
import mage.game.permanent.Permanent;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Full-engine smoke game: a real GameImpl runs its own loop (turns, priority,
 * stack, mana payment, state-based actions) with both players driven through
 * the CABT bridge — no stubs, no reflection proxies, real cards from the
 * engine's card classes. Proves that:
 * <ul>
 * <li>the bridge receives real priority prompts containing PASS_PRIORITY plus
 * engine-enumerated playable options,</li>
 * <li>selecting PLAY_LAND moves the actual card from hand to battlefield,</li>
 * <li>selecting CAST_SPELL drives the real cast → mana payment → stack →
 * resolve path until the creature is on the battlefield,</li>
 * <li>own-hand cards resolve to real names in serialized observations.</li>
 * </ul>
 */
@Timeout(120)
class CabtRealGameSmokeTest {

    private CabtSmokeDuel game;
    private GreedyPolicyBridgeController alicePolicy;
    private RecordingBridgeController aliceBridge;
    private CabtBridgePlayer alice;
    private GreedyPolicyBridgeController bobPolicy;
    private CabtBridgePlayer bob;
    private CabtRunRecorder runRecorder;

    private void startSmokeGame() {
        game = new CabtSmokeDuel();

        // both players' decisions flow through one globally-ordered run log,
        // from which the smoke-run artifact bundle is generated
        runRecorder = new CabtRunRecorder();
        alicePolicy = new GreedyPolicyBridgeController();
        aliceBridge = new RecordingBridgeController(
                runRecorder.wrap(alicePolicy), new MagicObservationSerializer());
        alice = new CabtBridgePlayer("Alice", RangeOfInfluence.ALL, aliceBridge);
        bobPolicy = new GreedyPolicyBridgeController();
        bob = new CabtBridgePlayer("Bob", RangeOfInfluence.ALL, runRecorder.wrap(bobPolicy));

        Deck emptyDeck1 = new Deck();
        Deck emptyDeck2 = new Deck();
        game.loadCards(emptyDeck1.getCards(), alice.getId());
        game.addPlayer(alice, emptyDeck1);
        game.loadCards(emptyDeck2.getCards(), bob.getId());
        game.addPlayer(bob, emptyDeck2);

        // Alice: Forest + Grizzly Bears in hand, Forests in the library.
        // Turn 1: play Forest. Turn 2: draw + play a second Forest, cast the
        // bears ({1}{G}) paying with both Forests, let it resolve.
        game.cheat(alice.getId(),
                cards(alice.getId(), forest(), forest(), forest(), forest()),
                cards(alice.getId(), forest(), bears()),
                Collections.<PutToBattlefieldInfo>emptyList(),
                Collections.<Card>emptyList(),
                Collections.<Card>emptyList(),
                Collections.<Card>emptyList());
        // Bob: lands only, so his greedy policy just plays a land and passes.
        game.cheat(bob.getId(),
                cards(bob.getId(), forest(), forest(), forest(), forest()),
                cards(bob.getId(), forest()),
                Collections.<PutToBattlefieldInfo>emptyList(),
                Collections.<Card>emptyList(),
                Collections.<Card>emptyList(),
                Collections.<Card>emptyList());

        GameOptions options = new GameOptions();
        options.testMode = true;
        options.skipInitShuffling = true;
        options.stopOnTurn = 3;
        options.stopAtStep = PhaseStep.END_TURN;
        game.setGameOptions(options);

        game.start(alice.getId());
    }

    @Test
    void bridgePlaysLandAndCastsCreatureThroughRealEngine() {
        startSmokeGame();

        // the real engine handed Alice priority prompts with playable options;
        // outside her main phase they are pass-only (a land play is not legal
        // at upkeep), so look for the first prompt that offers the land
        List<PendingDecision> priorityPrompts = decisionsOfType(alicePolicy, MagicSelectType.PRIORITY);
        assertThat(priorityPrompts).isNotEmpty();
        assertThat(priorityPrompts.get(0).options().get(0).type())
                .isEqualTo(MagicOptionType.PASS_PRIORITY);
        PendingDecision landPrompt = null;
        for (PendingDecision decision : priorityPrompts) {
            if (optionTypes(decision).contains(MagicOptionType.PLAY_LAND)) {
                landPrompt = decision;
                break;
            }
        }
        assertThat(landPrompt).as("a priority prompt offering PLAY_LAND").isNotNull();
        MagicOption landOption = null;
        for (MagicOption option : landPrompt.options()) {
            if (option.type() == MagicOptionType.PLAY_LAND) {
                landOption = option;
            }
        }
        assertThat(landOption.payload().get("sourceName")).isEqualTo("Forest");

        // selecting PLAY_LAND and CAST_SPELL changed real game state:
        // two Forests and the resolved Grizzly Bears under Alice's control
        List<String> aliceBattlefield = new ArrayList<String>();
        for (Permanent permanent : game.getBattlefield().getAllActivePermanents(alice.getId())) {
            aliceBattlefield.add(permanent.getName());
        }
        assertThat(aliceBattlefield)
                .containsExactlyInAnyOrder("Forest", "Forest", "Grizzly Bears");
        assertThat(alice.getHand().getCards(game)).isEmpty();

        // the cast went through the real mana-payment loop
        List<PendingDecision> manaPrompts = decisionsOfType(alicePolicy, MagicSelectType.PAY_MANA);
        assertThat(manaPrompts).isNotEmpty();
        assertThat(optionTypes(manaPrompts.get(0))).contains(MagicOptionType.PROMPT_MANA_SOURCE);

        // and the decisions were traced through to APPLIED
        assertThat(selectedTraceTypes(alice))
                .contains(MagicOptionType.PLAY_LAND, MagicOptionType.CAST_SPELL,
                        MagicOptionType.PROMPT_MANA_SOURCE);
        for (CabtDecisionTrace trace : alice.getTraceRecorder().getTraces()) {
            assertThat(trace.getStage()).isEqualTo(CabtDecisionTrace.Stage.APPLIED);
        }

        // Bob's side of the same engine loop worked too
        List<String> bobBattlefield = new ArrayList<String>();
        for (Permanent permanent : game.getBattlefield().getAllActivePermanents(bob.getId())) {
            bobBattlefield.add(permanent.getName());
        }
        assertThat(bobBattlefield).contains("Forest");
    }

    @Test
    void ownHandCardsResolveToRealNamesInObservations() {
        startSmokeGame();

        // the first priority observation was serialized from the live game:
        // Alice sees her own hand with real card names
        MagicObservation first = firstObservationOfType(aliceBridge, "PRIORITY");
        assertThat(first).isNotNull();
        MagicPlayerView aliceView = null;
        for (MagicPlayerView playerView : first.getCurrent().getPlayers()) {
            if (playerView.getName().equals("Alice")) {
                aliceView = playerView;
            }
        }
        assertThat(aliceView).isNotNull();
        List<String> handNames = new ArrayList<String>();
        for (MagicObjectView cardView : aliceView.getHand()) {
            handNames.add(cardView.getRef().getName());
        }
        assertThat(handNames).containsExactlyInAnyOrder("Forest", "Grizzly Bears");
    }

    @Test
    void smokeRunBundleIsGeneratedAndInternallyConsistent() throws Exception {
        startSmokeGame();

        java.io.File bundleDir = new java.io.File("target/cabt-smoke-run");
        Map<String, Object> manifest = new LinkedHashMap<String, Object>();
        manifest.put("testName", "play_land_cast_grizzly_bears");
        manifest.put("generator", getClass().getName());
        manifest.put("stopOnTurn", 3);
        Map<String, Object> decklists = new LinkedHashMap<String, Object>();
        decklists.put("alice", decklist(
                java.util.Arrays.asList("Forest", "Grizzly Bears"),
                java.util.Arrays.asList("Forest", "Forest", "Forest", "Forest")));
        decklists.put("bob", decklist(
                java.util.Arrays.asList("Forest"),
                java.util.Arrays.asList("Forest", "Forest", "Forest", "Forest")));

        CabtSmokeRunBundleWriter.Result result = new CabtSmokeRunBundleWriter(bundleDir).write(
                manifest, decklists, runRecorder.getSteps(), runRecorder.finalState(game, alice));

        // every artifact exists and is non-empty
        for (String fileName : new String[]{"manifest.json", "decklists.json",
                "observations.jsonl", "transitions.jsonl", "timeline.html",
                "final-state.json", "invariants.json"}) {
            java.io.File file = new java.io.File(bundleDir, fileName);
            assertThat(file).as(fileName).exists();
            assertThat(file.length()).as(fileName + " is non-empty").isGreaterThan(0);
        }

        // the writer's cross-file invariants all hold: PLAY_LAND moved its
        // card HAND->BATTLEFIELD, CAST_SPELL moved it HAND->STACK, the mana
        // source tapped, a spell resolved STACK->BATTLEFIELD, moves chain,
        // the final battlefield agrees, and no opponent hand leaked
        assertThat(result.getFailedChecks()).isEmpty();
        assertThat(result.isPassed()).isTrue();

        // spot-check the evidence from outside the writer: the resolved
        // spell named in invariants.json is the Grizzly Bears, and the
        // transitions file records the STACK->BATTLEFIELD move
        String invariants = new String(java.nio.file.Files.readAllBytes(
                new java.io.File(bundleDir, "invariants.json").toPath()),
                java.nio.charset.StandardCharsets.UTF_8);
        assertThat(invariants).contains("Grizzly Bears");
        assertThat(invariants).contains("transitionSequence");
        String transitions = new String(java.nio.file.Files.readAllBytes(
                new java.io.File(bundleDir, "transitions.jsonl").toPath()),
                java.nio.charset.StandardCharsets.UTF_8);
        assertThat(transitions).contains("\"from\":\"STACK\",\"to\":\"BATTLEFIELD\"");
        assertThat(transitions).contains("\"from\":\"HAND\",\"to\":\"BATTLEFIELD\"");
    }

    private static Map<String, Object> decklist(List<String> openingHand, List<String> libraryTopFirst) {
        Map<String, Object> decklist = new LinkedHashMap<String, Object>();
        decklist.put("openingHand", openingHand);
        decklist.put("libraryTopFirst", libraryTopFirst);
        return decklist;
    }

    // --- fixtures ---

    private static Card forest() {
        return new Forest(null, new CardSetInfo("Forest", "TEST", "1", Rarity.LAND));
    }

    private static Card bears() {
        return new GrizzlyBears(null, new CardSetInfo("Grizzly Bears", "TEST", "2", Rarity.COMMON));
    }

    private static List<Card> cards(UUID ownerId, Card... cards) {
        List<Card> list = new ArrayList<Card>();
        for (Card card : cards) {
            card.setOwnerId(ownerId);
            list.add(card);
        }
        return list;
    }

    private static List<PendingDecision> decisionsOfType(GreedyPolicyBridgeController policy,
                                                         MagicSelectType type) {
        List<PendingDecision> found = new ArrayList<PendingDecision>();
        for (PendingDecision decision : policy.getDecisions()) {
            if (decision.selectType() == type) {
                found.add(decision);
            }
        }
        return found;
    }

    private static List<MagicOptionType> optionTypes(PendingDecision decision) {
        List<MagicOptionType> types = new ArrayList<MagicOptionType>();
        for (MagicOption option : decision.options()) {
            types.add(option.type());
        }
        return types;
    }

    /**
     * Option types the player actually selected, across all traced decisions.
     */
    private static List<MagicOptionType> selectedTraceTypes(CabtBridgePlayer player) {
        List<MagicOptionType> selected = new ArrayList<MagicOptionType>();
        for (CabtDecisionTrace trace : player.getTraceRecorder().getTraces()) {
            if (trace.getSelection() == null) {
                continue;
            }
            for (int index : trace.getSelection().indices()) {
                selected.add(trace.getDecision().options().get(index).type());
            }
        }
        return selected;
    }

    private static MagicObservation firstObservationOfType(RecordingBridgeController bridge,
                                                           String selectType) {
        for (MagicObservation observation : bridge.getObservations()) {
            if (observation.getSelect().getType().equals(selectType)) {
                return observation;
            }
        }
        return null;
    }
}
