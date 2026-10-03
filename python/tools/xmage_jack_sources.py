"""Stage Jack's private April encoder for an explicit permitted player view.

The source stays outside public Git. This prepares base-state and priority
candidate encoding; other callbacks, deck associations and games are unfinished.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from xmage_release_assets import prepare_root, validate_asset, verify


ENCODER_SHA256 = "51504c1ffffbf5db8554258b5dca28f54f26bb7760121e0098561eac0b14b916"
CALLBACK_SHA256 = "b45257a66fc3914506fca4dd83461b6c8853d129b3e1f38b2d3aeba6137bd0c6"
VARIANT = ("acting-player perspective; entity tokens limited to named permitted references; "
           "only explicitly known library cards, ordered by public object alias; "
           "pinned read-only text embeddings with no generated fallback")

CONTEXT = """
    private static final ThreadLocal<UUID> FAIR_VIEWER = new ThreadLocal<>();
    private static final ThreadLocal<Map<UUID, String>> FAIR_ALIASES = new ThreadLocal<>();

    private static java.util.Collection<? extends Card> visibleLibrary(
            java.util.Collection<? extends Card> cards) {
        List<Card> known = new ArrayList<>();
        for (Card card : cards) {
            if (FAIR_ALIASES.get().containsKey(card.getId())) known.add(card);
        }
        known.sort(java.util.Comparator.comparing(card -> FAIR_ALIASES.get().get(card.getId())));
        return known;
    }
"""


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("pinned Jack source lacks one unambiguous compatibility edit")
    return source.replace(before, after, 1)


def fair_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != ENCODER_SHA256:
        raise ValueError("Jack fair port requires the pinned April encoder bytes")
    source = replace_once(source, "package mage.player.ai.rl;", "package spellbench.models.jack;")
    source = replace_once(source, "public class StateSequenceBuilder {",
                          "public class StateSequenceBuilder {" + CONTEXT)
    source = replace_once(source,
        "public static SequenceOutput buildBaseState(Game game, TurnPhase phase, int maxLen) {",
        """public static SequenceOutput buildBaseState(Game game, TurnPhase phase, int maxLen,
            UUID viewer, Map<UUID, String> permittedAliases) {
        if (viewer == null || game.getPlayer(viewer) == null || permittedAliases == null
                || FAIR_VIEWER.get() != null) {
            throw new IllegalArgumentException("explicit non-reentrant permitted viewer required");
        }
        java.util.Set<String> aliases = new java.util.HashSet<>();
        for (Map.Entry<UUID, String> entry : permittedAliases.entrySet()) {
            if (entry.getKey() == null || entry.getValue() == null || entry.getValue().isEmpty()
                    || !aliases.add(entry.getValue())) {
                throw new IllegalArgumentException("permitted object aliases must be unique and nonempty");
            }
        }
        FAIR_VIEWER.set(viewer);
        FAIR_ALIASES.set(new HashMap<>(permittedAliases));
        try {""")
    start = source.index("        Player player = game.getPlayer(game.getActivePlayerId());")
    end = source.index("\n        /*", start)
    source = source[:start] + "        Player player = game.getPlayer(viewer);\n" + source[end:]
    source = replace_once(source, "return new SequenceOutput(tokens, mask, tokenIds, uuidMap);",
        """return new SequenceOutput(tokens, mask, tokenIds, uuidMap);
        } finally {
            FAIR_ALIASES.remove();
            FAIR_VIEWER.remove();
        }""")
    source = replace_once(source, "player.getLibrary().getCards(game)",
                          "visibleLibrary(player.getLibrary().getCards(game))")
    source = replace_once(source, "for (Permanent p : perms) {",
                          "for (Permanent p : perms) {\n            if (!FAIR_ALIASES.get().containsKey(p.getId())) continue;")
    source = replace_once(source, "for (StackObject so : game.getStack()) {",
                          "for (StackObject so : game.getStack()) {\n            if (!FAIR_ALIASES.get().containsKey(so.getId())) continue;")
    source = replace_once(source, "Map<UUID, Integer> uuidMap, Card c, Zone z, Game g) {",
                          "Map<UUID, Integer> uuidMap, Card c, Zone z, Game g) {\n"
                          "        if (!FAIR_ALIASES.get().containsKey(c.getId())) return;")
    for owner in ("controllerId", "card.getOwnerId()"):
        source = replace_once(source, owner + ".equals(game.getActivePlayerId())",
                              owner + ".equals(FAIR_VIEWER.get())")
    embedding = "CardTextEmbeddings.getInstance().getEmbedding("
    if source.count(embedding) != 2:
        raise ValueError("pinned Jack source changed its text-embedding calls")
    source = source.replace(embedding, "EmbeddingCache.getEmbedding(")
    return source


def extract(source: str, start: str, end: str) -> str:
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError("pinned Jack callback lacks unambiguous extraction boundaries")
    return source[source.index(start):source.index(end, source.index(start))].rstrip() + "\n"


def candidate_source(source: str) -> str:
    if hashlib.sha256(source.encode()).hexdigest() != CALLBACK_SHA256:
        raise ValueError("Jack priority port requires the pinned April callback bytes")
    methods = extract(source, "    private static int toVocabId(String key) {",
                      "    private double computeStepReward(")
    helpers = extract(source, "    private int getOpponentLife(Game game) {",
                      "    /**\n     * Set the current episode number for logging purposes.")
    combat = extract(source, "    static class CombatCandidate {", "\n}\n\n// Helper class to store block options")
    # The April callback reads these fields from the player object. The
    # standalone port uses the acting player already in the permitted world.
    methods = methods.replace("this.getId()", "viewer.getId()").replace("this.getLife()", "viewer.getLife()")
    methods = methods.replace("getHand()", "viewer.getHand()")
    methods = methods.replace("getManaAvailable(game)", "viewer.getManaAvailable(game)")
    helpers = helpers.replace("playerId", "viewer.getId()")
    methods = replace_once(methods, "        } catch (Exception e) {\n            return 0;\n        }",
                           "        } catch (Exception e) {\n            throw new IllegalArgumentException(\"Jack candidate ID failed\", e);\n        }")
    methods = replace_once(methods, "        } catch (Exception e) {\n            // leave zeros\n        }",
                           "        } catch (Exception e) {\n            throw new IllegalArgumentException(\"Jack candidate features failed\", e);\n        }")
    return """package spellbench.models.jack;

import mage.MageObject;
import mage.abilities.Ability;
import mage.abilities.SpellAbility;
import mage.abilities.common.PassAbility;
import mage.abilities.keyword.*;
import mage.counters.CounterType;
import mage.game.Game;
import mage.game.permanent.Permanent;
import mage.game.permanent.PermanentToken;
import mage.players.Player;
import java.util.UUID;

/** Private source extraction. Only the original priority feature path is exposed. */
public final class CandidateEncoder {
    public static final String SOURCE_SHA256 = "%s";
    private final Player viewer;
    public CandidateEncoder(Player viewer) {
        if (viewer == null) throw new IllegalArgumentException("acting player required");
        this.viewer = viewer;
    }
    public int priorityId(Game game, Ability candidate) {
        return computeCandidateActionId(StateSequenceBuilder.ActionType.ACTIVATE_ABILITY_OR_SPELL,
                game, null, candidate);
    }
    public float[] priorityFeatures(Game game, Ability candidate, StateSequenceBuilder.SequenceOutput state) {
        return computeCandidateFeatures(StateSequenceBuilder.ActionType.ACTIVATE_ABILITY_OR_SPELL,
                game, null, candidate, 48, state);
    }
""" % CALLBACK_SHA256 + methods + helpers + combat + "}\n"


def stage(manifest: dict, root: Path, output: Path) -> dict:
    if manifest.get("schema") != "spellbench-xmage-release-inputs/v1":
        raise ValueError("unknown release input manifest")
    config = manifest.get("inference_backends", {}).get("jack-rl-april", {})
    matches = [a for a in manifest.get("assets", []) if a.get("id") == config.get("state_encoder")]
    if len(matches) != 1:
        raise ValueError("Jack stage needs one private encoder asset")
    asset = matches[0]
    validate_asset(asset)
    if asset["sha256"] != ENCODER_SHA256 or asset.get("transport") != "local-file":
        raise ValueError("Jack stage requires the pinned private local encoder")
    root = prepare_root(root)
    verify(root / asset["filename"], asset)
    original = (root / asset["filename"]).read_bytes()
    modified = fair_source(original.decode("utf-8")).encode("utf-8")
    callbacks = [a for a in manifest.get("assets", []) if a.get("id") == config.get("callback_source")]
    if len(callbacks) != 1:
        raise ValueError("Jack stage needs one private callback asset")
    callback = callbacks[0]
    validate_asset(callback)
    if callback["sha256"] != CALLBACK_SHA256 or callback.get("transport") != "local-file":
        raise ValueError("Jack priority stage requires the pinned private local callback")
    verify(root / callback["filename"], callback)
    candidates = candidate_source((root / callback["filename"]).read_bytes().decode("utf-8")).encode("utf-8")
    if output.exists() or output.is_symlink():
        raise ValueError("Jack source stage needs a new owned output directory")
    output = prepare_root(output)
    with (output / "StateSequenceBuilder.java").open("xb") as stream:
        stream.write(modified)
    with (output / "CandidateEncoder.java").open("xb") as stream:
        stream.write(candidates)
    result = {"schema": "spellbench-jack-encoder-stage/v1", "original_source_sha256": asset["sha256"],
              "staged_source_sha256": hashlib.sha256(modified).hexdigest(), "variant": VARIANT,
              "original_callback_sha256": callback["sha256"],
              "staged_candidate_sha256": hashlib.sha256(candidates).hexdigest(),
              "candidate_scope": "original priority IDs and 48 features; explicit acting player; extraction failures refuse",
              "scope": "base-state and priority features; no other callbacks, deck qualification or games",
              "private_source": True, "embedding_source": "explicit hash-pinned offline cache"}
    with (output / "STAGE.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage(json.loads(args.manifest.read_bytes()), args.inputs, args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
