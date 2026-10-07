package spellbench.kit.xmage;

import mage.game.Game;
import mage.cards.*;
import mage.constants.*;
import mage.abilities.Ability;
import spellbench.models.maintainer.OriginalParentDialogsPlayer;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.util.*;
import static spellbench.kit.xmage.MaintainerPlayerBootstrapCheck.*;

/** Pinned PlayerImpl movement loop and original inherited selector on metadata placement worlds. */
public final class MaintainerLibraryOrderCheck {
    static boolean place(Card card,Game game,boolean top) {
        mage.players.Player p=game.getPlayer(card.getOwnerId());p.getHand().remove(card.getId());p.getLibrary().remove(card.getId(),game);
        if(top)p.getLibrary().putOnTop(card,game);else p.getLibrary().putOnBottom(card,game);
        game.getState().setZone(card.getId(),Zone.LIBRARY);return true;
    }
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
        @Override public boolean choose(mage.constants.Outcome o,mage.cards.Cards cards,mage.target.TargetCard target,mage.abilities.Ability a,Game g) {return originalParentCards(o,cards,target,a,g);}
        @Override public boolean chooseTarget(mage.constants.Outcome o,mage.cards.Cards cards,mage.target.TargetCard target,mage.abilities.Ability a,Game g) {return originalParentCards(o,cards,target,a,g);}
        @Override public boolean moveCardToLibraryWithInfo(mage.cards.Card card,mage.abilities.Ability source,Game game,mage.constants.Zone from,boolean top,boolean withName) {return place(card,game,top);}
    }
    static final class Case {
        final MaintainerDialogReplayCheck.Case c;
        final List<UUID> input,order;
        final boolean top;
        final Ability source;
        final Map<String,Object> before,after;
        Case(int count,boolean top,boolean hasSource) throws Exception {
            this.top=top;c=new MaintainerDialogReplayCheck.Case(count,true);c.player.libraryMetadata=true;c.player.updateRange(c.world.game);
            input=new ArrayList<>(c.player.getHand());source=hasSource?c.ability:null;before=c.decision("use");
            Oracle oracle=new Oracle(c.player);
            oracle.admitted=(Game)java.lang.reflect.Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                if("getPlayer".equals(m.getName()) && oracle.getId().equals(a[0]))return oracle;
                try{return m.invoke(c.world.game,a);}catch(java.lang.reflect.InvocationTargetException failure){throw failure.getCause();}
            });
            MaintainerAmountReplayCheck.random(3);
            require(top?oracle.putCardsOnTopOfLibrary(new CardsImpl(input),oracle.admitted,source,true):oracle.putCardsOnBottomOfLibrary(new CardsImpl(input),oracle.admitted,source,true),"parent library oracle failed");
            List<UUID> library=oracle.getLibrary().getCardList();order=new ArrayList<>(library.subList(top?0:library.size()-count,top?count:library.size()));
            for(UUID id:input)c.world.game.getState().setZone(id,Zone.HAND);
            MaintainerAmountReplayCheck.random(3);
            require(top?c.player.putCardsOnTopOfLibrary(new CardsImpl(input),c.world.game,source,true):c.player.putCardsOnBottomOfLibrary(new CardsImpl(input),c.world.game,source,true),"bare inherited library loop failed");
            List<UUID> actual=c.player.getLibrary().getCardList();require(order.equals(actual.subList(top?0:actual.size()-count,top?count:actual.size())),"callback wrapper changed its inherited parent ordering");
            after=c.decision("use");
            for(UUID id:input){c.player.getLibrary().remove(id,c.world.game);c.player.getHand().add(id);c.world.game.getState().setZone(id,Zone.HAND);}
            require(Json.canonical(before.get("observation")).equals(Json.canonical(c.decision("use").get("observation"))),"metadata oracle did not restore exact root");
            require(c.backend.calls==0 && c.backend.copies==0,"original inherited ordering scored a model/copy");
        }
        Map<String,Object> menu(int position) {
            Map<String,Object> d=Json.obj(Json.copy(before));List<Object> candidates=new ArrayList<>();
            List<UUID> remaining=new ArrayList<>(input);remaining.removeAll(order.subList(0,position));ObsIndex observed=new ObsIndex(Json.obj(d,"observation"));
            Object ref=source==null?null:observed.ref(c.world.uuidToId.get(source.getSourceId()));
            for(UUID id:remaining)candidates.add(Json.map("candidate_id",900L+candidates.size(),"semantic",Json.map("kind","order_pick","source",ref,"purpose",top?"library_top":"library_bottom",
                    "item",Json.map("object",observed.ref(c.world.uuidToId.get(id))),"position",(long)position,"count",(long)input.size())));
            d.put("candidates",candidates);d.put("group",Json.map("group_id",701L,"substep_index",(long)position,"substep_count",(long)input.size()-1));return d;
        }
        Map<String,Object> selected(Map<String,Object> d,int position) {
            String wanted=c.world.uuidToId.get(order.get(position));
            for(Object item:Json.arr(d,"candidates")) {
                Map<String,Object> candidate=Json.obj(item),semantic=Json.obj(candidate,"semantic");
                if(wanted.equals(Json.str(Json.obj(Json.obj(semantic,"item"),"object"),"object_id")))return Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",Json.copy(semantic));
            }
            throw new AssertionError("oracle card not offered");
        }
        Map<String,Object> record(int prefix) {
            Map<String,Object> r=c.record(false);List<Object> earlier=new ArrayList<>();
            for(int i=0;i<prefix;i++){Map<String,Object> d=menu(i);earlier.add(Json.map("decision",d,"selection",selected(d,i)));}
            Json.obj(r,"replay").put("earlier",earlier);r.put("decision",prefix==input.size()-1?after:menu(prefix));
            c.player.activationWork=()->{
                require(top?c.player.putCardsOnTopOfLibrary(new CardsImpl(input),c.world.game,source,true):c.player.putCardsOnBottomOfLibrary(new CardsImpl(input),c.world.game,source,true),"original physical ordering failed");
                c.player.chooseUse(Outcome.Benefit,"after original library ordering",null,c.world.game);
            };
            MaintainerAmountReplayCheck.random(3);return r;
        }
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();
        for(int count:new int[]{2,3,4,6})for(boolean top:new boolean[]{false,true})for(boolean source:new boolean[]{false,true})for(int prefix=0;prefix<count;prefix++) {
            Case c=new Case(count,top,source);Map<String,Object> r=c.record(prefix),result=new MaintainerDialogReplay(c.c.world,r).choose();
            require(Long.valueOf(prefix).equals(result.get("original_dialog_prefix_replayed")),"library prefix incomplete");
            boolean after=prefix==count-1;
            if(!after)require(Json.canonical(c.selected(Json.obj(r,"decision"),prefix)).equals(Json.canonical(result.get("selection"))),"wire order differs from actual unchanged parent placement");
            require(c.c.backend.calls==(after?1:0) && c.c.backend.copies==0 && !c.c.backend.closed,"ordering changed policy/copy draws or closed session");
            rows.add(Json.map("count",(long)count,"top",top,"source",source,"prefix",(long)prefix,"matches_parent_oracle",true));c.c.registry.close();
        }
        for(String fault:Arrays.asList("hole","duplicate","source","position","count","group","history","hidden-card","changed-observation")) {
            Case c=new Case(4,true,false);boolean history="history".equals(fault);Map<String,Object> r=c.record(history?1:0),d=Json.obj(r,"decision"),candidate=Json.obj(Json.arr(d,"candidates").get(0)),s=Json.obj(candidate,"semantic");
            if("hole".equals(fault))Json.arr(d,"candidates").remove(0);
            if("duplicate".equals(fault))candidate.put("candidate_id",901L);
            if("source".equals(fault))s.put("source",Json.obj(s,"item").get("object"));
            if("position".equals(fault))s.put("position",1L);
            if("count".equals(fault))s.put("count",5L);
            if("group".equals(fault))Json.obj(d,"group").put("substep_count",4L);
            if("history".equals(fault)) {
                Map<String,Object> entry=Json.obj(Json.arr(Json.obj(r,"replay"),"earlier").get(0)),initial=Json.obj(entry,"decision");
                Object chosen=Json.obj(entry,"selection").get("candidate_id");
                for(Object item:Json.arr(initial,"candidates")){Map<String,Object> other=Json.obj(item);if(!chosen.equals(other.get("candidate_id"))){entry.put("selection",Json.map("candidate_id",other.get("candidate_id"),"semantic_echo",other.get("semantic")));break;}}
            }
            if("hidden-card".equals(fault))c.c.player.activationWork=()->c.c.player.putCardsOnTopOfLibrary(new CardsImpl(c.c.player.getLibrary().getCardList()),c.c.world.game,null,true);
            if("hidden-card".equals(fault)){c.c.player.getLibrary().putOnTop(c.c.root.cards.get(c.input.get(0)),c.c.world.game);c.c.player.getHand().remove(c.input.get(0));}
            if("changed-observation".equals(fault))Json.obj(d,"observation").put("turn",2L);
            refused(()->new MaintainerDialogReplay(c.c.world,r).choose());require(c.c.backend.calls==0 && c.c.backend.copies==0 && c.c.backend.closed,"invalid library order scored or kept session");
        }
        System.out.println(Json.canonical(rows));
        System.out.println("MaintainerLibraryOrderCheck PASS: original PlayerImpl loops and pinned inherited selection oracle, complete top/bottom physical blocks, repeated names, whole wire groups and prefixes with zero inherited policy/copy draws; metadata movement only, native ordering unqualified");
    }
}
