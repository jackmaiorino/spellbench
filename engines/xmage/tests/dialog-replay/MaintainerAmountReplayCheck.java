package spellbench.kit.xmage;

import mage.game.Game;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import spellbench.kit.core.Seeds;
import spellbench.models.maintainer.OriginalParentDialogsPlayer;
import java.lang.reflect.*;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Original inherited amount body as oracle; no native game or trained model. */
public final class MaintainerAmountReplayCheck {
    static final class Oracle extends OriginalParentDialogsPlayer {
        Game admitted;
        Oracle(mage.player.ai.ComputerPlayer old) {super(old);}
        Oracle(Oracle old) {super(old);}
        @Override public Oracle copy() {return new Oracle(this);}
        @Override protected void requireOriginalPermittedWorld(Game g) {require(g==admitted,"oracle world changed");}
        @Override public boolean priority(Game g) {throw new AssertionError("oracle priority");}
        @Override public void selectAttackers(Game g,UUID p) {throw new AssertionError("oracle attack");}
        @Override public void selectBlockers(mage.abilities.Ability a,Game g,UUID p) {throw new AssertionError("oracle block");}
        @Override public boolean chooseMulligan(Game g) {throw new AssertionError("oracle mulligan");}
        @Override public boolean chooseUse(mage.constants.Outcome o,String m,mage.abilities.Ability a,Game g) {throw new AssertionError("oracle use");}
        @Override public boolean chooseUse(mage.constants.Outcome o,String m,String second,String yes,String no,mage.abilities.Ability a,Game g) {throw new AssertionError("oracle use");}
        @Override public int announceX(int min,int max,String m,Game g,mage.abilities.Ability a,boolean mana) {throw new AssertionError("oracle X");}
        @Override public mage.abilities.Mode chooseMode(mage.abilities.Modes modes,mage.abilities.Ability a,Game g) {throw new AssertionError("oracle mode");}
        @Override public boolean choose(mage.constants.Outcome o,mage.choices.Choice choice,Game g) {throw new AssertionError("oracle choice");}
        @Override public boolean choose(mage.constants.Outcome o,mage.target.Target target,mage.abilities.Ability a,Game g) {throw new AssertionError("oracle target");}
        @Override public boolean chooseTarget(mage.constants.Outcome o,mage.target.Target target,mage.abilities.Ability a,Game g) {throw new AssertionError("oracle target");}
        @Override public boolean choose(mage.constants.Outcome o,mage.cards.Cards cards,mage.target.TargetCard target,mage.abilities.Ability a,Game g) {throw new AssertionError("oracle cards");}
        @Override public boolean chooseTarget(mage.constants.Outcome o,mage.cards.Cards cards,mage.target.TargetCard target,mage.abilities.Ability a,Game g) {throw new AssertionError("oracle cards");}
    }
    static KitRandom random(int seed) {byte[] value=Seeds.unhex(String.format("%064x",seed));return KitRandom.install(value,value);}
    static long draws(KitRandom random) {long count=0;for(Map.Entry<String,Long> e:random.usage().entrySet())if(!e.getKey().startsWith("ids:") && !e.getKey().equals("untagged_calls"))count+=e.getValue();return count;}
    static Map<String,Object> menu(MaintainerDialogReplayCheck.Case c,int min,int max,boolean source) {
        Map<String,Object> d=c.decision("use");Object ref=source?new ObsIndex(Json.obj(d,"observation")).ref(c.world.uuidToId.get(c.ability.getSourceId())):null;
        Json.obj(d,"context").put("source",ref);Json.obj(d,"context").put("purpose","amount");List<Object> choices=new ArrayList<>();
        long effective=max==Integer.MAX_VALUE?Math.max(min,10):max;
        for(long value=min;value<=effective;value++)choices.add(Json.map("candidate_id",200L+value-min,"semantic",Json.map(
                "kind","choose_number","purpose","amount","source",ref,"minimum",(long)min,"maximum",(long)max,"value",value)));
        d.put("candidates",choices);return d;
    }
    static Map<String,Object> record(MaintainerDialogReplayCheck.Case c,int min,int max,boolean source,boolean prefix) {
        Map<String,Object> r=c.record(false);r.put("decision",menu(c,min,max,source));
        if(prefix) {
            Map<String,Object> past=menu(c,0,3,source),candidate=Json.obj(Json.arr(past,"candidates").get(1));
            Json.obj(r,"replay").put("earlier",Collections.singletonList(Json.map("decision",past,"selection",Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",candidate.get("semantic")))));
        }
        c.player.activationWork=()->{
            if(prefix)c.player.getAmount(0,3,"earlier",source?c.ability:null,c.world.game);
            c.player.getAmount(min,max,"current",source?c.ability:null,c.world.game);
        };return r;
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();int[][] bounds={{0,3},{2,7},{65,90},{-2,3},{-3,-3},{4,4},{0,Integer.MAX_VALUE},{12,Integer.MAX_VALUE},{Integer.MAX_VALUE,Integer.MAX_VALUE}};
        for(int seed=0;seed<8;seed++)for(int[] range:bounds)for(boolean prefix:new boolean[]{false,true})for(boolean source:new boolean[]{false,true}) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case();Map<String,Object> r=record(c,range[0],range[1],source,prefix);
            Oracle oracle=new Oracle(c.player);oracle.admitted=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                if("getPlayer".equals(m.getName()) && oracle.getId().equals(a[0]))return oracle;
                try{return m.invoke(c.world.game,a);}catch(InvocationTargetException failure){throw failure.getCause();}
            });
            KitRandom expectedRandom=random(seed);
            if(prefix) {
                int past=oracle.getAmount(0,3,"earlier oracle",source?c.ability:null,oracle.admitted);
                Map<String,Object> pastEntry=Json.obj(Json.arr(Json.obj(r,"replay"),"earlier").get(0)),pastDecision=Json.obj(pastEntry,"decision"),candidate=Json.obj(Json.arr(pastDecision,"candidates").get(past));
                pastEntry.put("selection",Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",candidate.get("semantic")));
            }
            int expected=oracle.getAmount(range[0],range[1],"oracle",source?c.ability:null,oracle.admitted);long expectedDraws=draws(expectedRandom);
            KitRandom actualRandom=random(seed);Map<String,Object> result=c.control(r).choose();Map<String,Object> semantic=Json.obj(Json.obj(result,"selection"),"semantic_echo");
            require(Long.valueOf(expected).equals(semantic.get("value")) && draws(actualRandom)==expectedDraws,"original inherited amount or random stream consumption changed");
            require(c.backend.calls==0 && c.backend.copies==0 && !c.backend.closed,"amount used neural X/copy scoring or leaked its session");
            require(Long.valueOf(prefix?1:0).equals(result.get("original_dialog_prefix_replayed")),"amount prefix count changed");
            rows.add(Json.map("seed",(long)seed,"min",(long)range[0],"max",(long)range[1],"prefix",prefix,"source",source,"value",(long)expected,"random_draws",expectedDraws));c.registry.close();
        }
        for(String fault:Arrays.asList("purpose","hole","duplicate","fractional","bounds","source","actual-bounds","historical-draw")) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case();Map<String,Object> r=record(c,0,3,false,"historical-draw".equals(fault)),d=Json.obj(r,"decision"),first=Json.obj(Json.arr(d,"candidates").get(0)),sem=Json.obj(first,"semantic");
            if("purpose".equals(fault))sem.put("purpose","x_value");if("hole".equals(fault))Json.arr(d,"candidates").remove(0);
            if("duplicate".equals(fault))Json.obj(Json.obj(Json.arr(d,"candidates").get(1)),"semantic").put("value",0L);
            if("fractional".equals(fault))sem.put("value",0.5);if("bounds".equals(fault))sem.put("maximum",4L);
            if("source".equals(fault))Json.obj(d,"context").put("source",Json.map("object_id","hidden"));
            if("actual-bounds".equals(fault))c.player.activationWork=()->c.player.getAmount(1,4,"different",null,c.world.game);
            if("historical-draw".equals(fault)) {
                random(1);int wrong=(mage.util.RandomUtil.nextInt(4)+1)%4;
                Map<String,Object> past=Json.obj(Json.arr(Json.obj(r,"replay"),"earlier").get(0)),candidate=Json.obj(Json.arr(Json.obj(past,"decision"),"candidates").get(wrong));
                past.put("selection",Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",candidate.get("semantic")));
            }
            KitRandom current=random(1);refused(()->c.control(r).choose());require(("historical-draw".equals(fault)?draws(current)>0:draws(current)==0) && c.backend.calls==0 && c.backend.copies==0 && c.backend.closed,"invalid amount consumed unexpected random/scoring or retained session");
        }
        System.out.println(Json.canonical(rows));
        System.out.println("MaintainerAmountReplayCheck PASS: pinned inherited amount oracle, eight seeds, signed/fixed/high/capped bounds, visible sources, exact engine RNG restoration with zero neural/copy draws and pre-RNG structural refusal; metadata worlds only, native amount callbacks unqualified");
    }
}
