package spellbench.kit.xmage;

import mage.abilities.Ability;
import mage.abilities.ActivatedAbility;
import mage.abilities.Mode;
import mage.abilities.Modes;
import mage.abilities.common.PassAbility;
import mage.cards.Cards;
import mage.choices.Choice;
import mage.constants.Outcome;
import mage.constants.PhaseStep;
import mage.constants.RangeOfInfluence;
import mage.game.Game;
import mage.game.events.GameEvent;
import mage.game.stack.StackObject;
import mage.player.ai.ComputerPlayer7;
import mage.target.Target;
import mage.target.TargetAmount;
import mage.target.TargetCard;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;

import java.io.Serializable;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * H1 and H2's bot (design Section 5.2): the vendored {@code ComputerPlayer7} with the kit diff (synchronous search,
 * budgets, root statistics, horizon) deciding on one world, and the {@code ComputerPlayer} dialog heuristics for
 * choices outside plans. Its priority decision follows {@code ComputerPlayer7.priorityPlay} step by step; the first
 * action of the best chain is the answer (a chain is replanned at the next decision, Section 6.1).
 * <p>
 * While {@link #recording} is on, every dialog answer this player gives in the live world (not in simulations) is
 * recorded in order: what the executed object does not carry (Section 6.1 "Recording").
 */
public class KitMad extends ComputerPlayer7 {

    private static final long serialVersionUID = 1L;

    /** One recorded live dialog answer: family and value. */
    public static final class Answer {
        public final String family;
        public final Object value;

        Answer(String family, Object value) {
            this.family = family;
            this.value = value;
        }
    }

    public transient boolean setup = true;
    public transient boolean recording;
    public transient List<Answer> answers = new ArrayList<>();
    private transient World world;

    public KitMad(String name, int skill) {
        super(name, RangeOfInfluence.ALL, skill);
    }

    protected KitMad(final KitMad p) {
        super(p);
        this.setup = p.setup;
        this.recording = false;
        this.answers = new ArrayList<>();
        this.world = p.world;
    }

    @Override
    public KitMad copy() {
        return new KitMad(this);
    }

    public void attach(World w) {
        this.world = w;
        this.setup = false;
    }

    /** The outcome of one priority decision on one world. */
    public static final class PriorityOutcome {
        public boolean pass;
        public String reason;
        public Ability chosen;
        public Map<String, Object> semantic;
        public Map<String, Object> optionPayload;
        public Map<String, Object> executedPayload;
        public List<RootStat> stats = new ArrayList<>();
        public List<Map<String, Object>> statSemantics = new ArrayList<>();
        public List<Map<String, Object>> statPayloads = new ArrayList<>();
        public boolean activated;
        public List<Answer> answers = new ArrayList<>();
    }

    /** CP7 thinks in these steps and passes in the others (ComputerPlayer7.priorityPlay). */
    public static boolean thinksIn(PhaseStep s) {
        return s == PhaseStep.PRECOMBAT_MAIN || s == PhaseStep.DECLARE_ATTACKERS || s == PhaseStep.DECLARE_BLOCKERS
                || s == PhaseStep.POSTCOMBAT_MAIN;
    }

    /**
     * {@code ComputerPlayer7.priorityPlay} on the world, recording root statistics and keys; with {@code act}, the
     * first action is executed in the world and its payload read from the executed object.
     */
    public PriorityOutcome decidePriority(World w, ObsIndex obs, boolean act) {
        Game game = w.game;
        PriorityOutcome out = new PriorityOutcome();
        maxNodes = KitContext.nodeBudget;
        actions.clear();
        rootStats.clear();
        game.getState().setPriorityPlayerId(playerId);
        game.firePriorityEvent(playerId);
        if (!thinksIn(game.getTurnStepType())) {
            out.pass = true;
            out.reason = "cp7_passes_in_step";
            return out;
        }
        calculateActions(game);
        for (RootStat rs : rootStats) {
            out.stats.add(rs);
            out.statSemantics.add(Mapping.prioritySemantic(w, game, rs.ability, obs));
            out.statPayloads.add(Mapping.payload(w, rs.ability, game));
        }
        Ability first = actions.peek();
        if (first == null || first instanceof PassAbility) {
            out.pass = true;
            out.reason = first == null ? "no_action" : "pass";
            out.semantic = Json.map("kind", "pass");
            return out;
        }
        out.chosen = first;
        out.semantic = Mapping.prioritySemantic(w, game, first, obs);
        out.optionPayload = Mapping.payload(w, first, game);
        if (act) {
            execute(w, first, out);
        }
        return out;
    }

    /** ComputerPlayer6.act for the first action only, recording the live dialogs and the executed payload. */
    void execute(World w, Ability ability, PriorityOutcome out) {
        Game game = w.game;
        if (!ability.getTargets().isEmpty()) {
            for (Target target : ability.getTargets()) {
                for (UUID id : target.getTargets()) {
                    target.updateTarget(id, game);
                    if (!target.isNotTarget()) {
                        game.addSimultaneousEvent(GameEvent.getEvent(GameEvent.EventType.TARGETED, id, ability, ability.getControllerId()));
                    }
                }
            }
        }
        int before = game.getStack().size();
        answers = new ArrayList<>();
        recording = true;
        try {
            out.activated = this.activateAbility((ActivatedAbility) ability, game);
        } finally {
            recording = false;
        }
        out.answers = answers;
        if (out.activated && game.getStack().size() > before) {
            StackObject top = game.getStack().getFirstOrNull();
            out.executedPayload = Mapping.payload(w, Mapping.executedAbility(top), game);
        } else {
            out.executedPayload = new java.util.LinkedHashMap<>();
        }
    }

    // ------------------------------------------------------------------ setup and recording

    @Override
    public boolean chooseMulligan(Game game) {
        if (setup) {
            return false;
        }
        return super.chooseMulligan(game);
    }

    private boolean live(Game game) {
        return recording && game != null && !game.isSimulation();
    }

    private void record(Game game, String family, Object value) {
        if (live(game)) {
            answers.add(new Answer(family, value));
        }
    }

    private static List<Object> ids(World w, Target t) {
        List<Object> out = new ArrayList<>();
        for (UUID id : t.getTargets()) {
            out.add(w == null ? id.toString() : Mapping.targetRef(w, id));
        }
        return out;
    }

    @Override
    public boolean chooseTarget(Outcome outcome, Target target, Ability source, Game game) {
        boolean r = super.chooseTarget(outcome, target, source, game);
        record(game, "target", ids(world, target));
        return r;
    }

    @Override
    public boolean choose(Outcome outcome, Target target, Ability source, Game game, Map<String, Serializable> options) {
        if (setup) {
            return false;
        }
        boolean r = super.choose(outcome, target, source, game, options);
        record(game, "select", ids(world, target));
        return r;
    }

    @Override
    public boolean chooseTarget(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        boolean r = super.chooseTarget(outcome, cards, target, source, game);
        record(game, "target", ids(world, target));
        return r;
    }

    @Override
    public boolean choose(Outcome outcome, Cards cards, TargetCard target, Ability source, Game game) {
        boolean r = super.choose(outcome, cards, target, source, game);
        record(game, "select", ids(world, target));
        return r;
    }

    @Override
    public boolean chooseTargetAmount(Outcome outcome, TargetAmount target, Ability source, Game game) {
        boolean r = super.chooseTargetAmount(outcome, target, source, game);
        record(game, "target_amount", ids(world, target));
        return r;
    }

    @Override
    public boolean chooseUse(Outcome outcome, String message, String secondMessage, String trueText, String falseText,
                             Ability source, Game game) {
        if (setup) {
            return false;
        }
        boolean r = super.chooseUse(outcome, message, secondMessage, trueText, falseText, source, game);
        record(game, "use", r);
        return r;
    }

    @Override
    public Mode chooseMode(Modes modes, Ability source, Game game) {
        Mode m = super.chooseMode(modes, source, game);
        if (m != null) {
            long index = 0;
            for (Mode x : modes.values()) {
                if (x.getId().equals(m.getId())) {
                    break;
                }
                index++;
            }
            record(game, "mode", index);
        }
        return m;
    }

    @Override
    public int announceX(int min, int max, String message, Game game, Ability source, boolean isManaPay) {
        int x = super.announceX(min, max, message, game, source, isManaPay);
        record(game, "x", (long) x);
        return x;
    }

    @Override
    public int getAmount(int min, int max, String message, Ability source, Game game) {
        int x = super.getAmount(min, max, message, source, game);
        record(game, "amount", (long) x);
        return x;
    }

    @Override
    public boolean choose(Outcome outcome, Choice choice, Game game) {
        boolean r = super.choose(outcome, choice, game);
        record(game, "choice", choice.isKeyChoice() ? choice.getChoiceKey() : choice.getChoice());
        return r;
    }
}
