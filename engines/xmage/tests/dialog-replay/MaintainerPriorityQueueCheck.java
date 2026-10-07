package spellbench.kit.xmage;

import mage.game.Game;
import spellbench.kit.core.Json;
import java.lang.reflect.Method;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Original inherited target queue, captured and restored on metadata worlds. */
public final class MaintainerPriorityQueueCheck {
    static Object rules(MaintainerDialogReplayCheck.Case c) throws Exception {
        Method getter=Class.forName("spellbench.models.maintainer.OriginalPriorityChoicePlayer").getDeclaredMethod("originalPriorityRules");
        getter.setAccessible(true);return getter.invoke(c.player);
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();
        for(int count:new int[]{0,1,2,64}) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case(2,false);
            List<UUID> cards=new ArrayList<>(c.player.getHand()),expected=new ArrayList<>();
            for(int i=0;i<count;i++) {UUID id=cards.get(i%2);c.player.queueCard(id);expected.add(id);}
            Map<String,Object> root=Json.obj(Json.obj(c.record(false),"anchor"),"decision");Object rules=rules(c);
            Map<String,Object> state=MaintainerPriorityState.capture(c.world,root,rules);
            require(Json.arr(state,"targets").size()==count,"original target queue lost entries");
            c.player.restoreOriginalTargets(c.world.game,Collections.singletonList(cards.get(1)));
            MaintainerPriorityState.restore(c.world,root,state,c.ability,rules);
            require(c.player.queuedOriginalTargets(c.world.game).equals(expected),"restored target queue changed order, duplicates or replacement");
            if(count>0)Json.obj(Json.arr(state,"targets").get(0)).put("card_name","changed exported copy");
            require(c.player.queuedOriginalTargets(c.world.game).equals(expected),"exported queue shared original mutable state");
            List<UUID> exported=c.player.queuedOriginalTargets(c.world.game);exported.clear();
            require(c.player.queuedOriginalTargets(c.world.game).equals(expected),"queue getter borrowed the original list");
            require(c.backend.calls==0 && c.backend.copies==0,"queue restoration drew from policy or chooser");
            rows.add(Json.map("count",(long)count,"ordered_duplicates_preserved",true,"model_calls",0L,"copy_draws",0L));c.registry.close();
        }
        for(String fault:new String[]{"missing","hidden","changed","extra","oversized"}) {
            MaintainerDialogReplayCheck.Case c=new MaintainerDialogReplayCheck.Case(2,false);c.player.queueCard(c.player.getHand().iterator().next());
            Map<String,Object> record=c.record(false),state=Json.obj(Json.obj(record,"anchor"),"original_priority_state");
            if("missing".equals(fault))state.remove("targets");
            if("hidden".equals(fault))Json.obj(Json.arr(state,"targets").get(0)).put("object_id","hidden");
            if("changed".equals(fault))Json.obj(Json.arr(state,"targets").get(0)).put("card_name","other name");
            if("extra".equals(fault))Json.obj(Json.arr(state,"targets").get(0)).put("private",true);
            if("oversized".equals(fault))state.put("targets",Collections.nCopies(4097,Json.arr(state,"targets").get(0)));
            refused(()->c.control(record).choose());
            require(c.backend.closed && c.backend.calls==0 && c.backend.copies==0 && c.player.entered==0,"malformed queue activated or advanced original session");
        }
        MaintainerDialogReplayCheck.Case hidden=new MaintainerDialogReplayCheck.Case();hidden.player.queueCard(hidden.player.getLibrary().getCardList().get(0));
        Map<String,Object> root=Json.obj(Json.obj(hidden.record(false),"anchor"),"decision");Object rules=rules(hidden);
        refused(()->{
            try {MaintainerPriorityState.capture(hidden.world,root,rules);}
            catch(Exception failure) {throw new IllegalArgumentException("metadata hidden queue rejected",failure);}
        });
        require(hidden.backend.calls==0 && hidden.backend.copies==0,"hidden queue capture drew from model");hidden.registry.close();
        System.out.println(Json.canonical(rows));System.out.println("MaintainerPriorityQueueCheck PASS: complete ordered queue, duplicates, independent copies, exact permitted references and pre-activation refusal; metadata worlds only");
    }
}
