package spellbench.kit.xmage;

import mage.MageObject;
import mage.cards.Card;
import mage.constants.Outcome;
import mage.game.Game;
import spellbench.kit.core.Json;
import spellbench.kit.core.ObsIndex;
import java.lang.reflect.*;
import java.util.*;
import static spellbench.kit.xmage.JackPlayerBootstrapCheck.*;

/** Exercise unchanged inherited policies through the original replay on metadata worlds. */
public final class JackInheritedReplayCheck {
    static final class Menu {
        final JackDialogReplayCheck.Case c=new JackDialogReplayCheck.Case(3,true);
        final List<Card> left=new ArrayList<>(),right=new ArrayList<>();
        final Map<String,String> effects;
        final Map<String,MageObject> objects=new LinkedHashMap<>();
        final String kind;final boolean sourced;
        Menu(String kind,int count,boolean sourced,boolean unordered) {
            this.kind=kind;this.sourced=sourced;effects=unordered?new HashMap<>():new LinkedHashMap<>();
            List<UUID> hand=new ArrayList<>(c.player.getHand());
            left.add(c.root.cards.get(hand.get(0)));left.add(c.root.cards.get(hand.get(1)));
            right.add(c.root.cards.get(hand.get(2)));
            for(int i=0;i<count;i++) {
                String key="effect-"+(count-i);effects.put(key,"same visible label");
                if(sourced)objects.put(key,c.root.cards.get(hand.get(i%hand.size())));
            }
        }
        Object ref(Card card,Map<String,Object> d) {
            return new ObsIndex(Json.obj(d,"observation")).ref(c.world.uuidToId.get(card.getId()));
        }
        Map<String,Object> decision() {
            Map<String,Object> d=c.decision("use");Json.obj(d,"context").put("source",null);
            List<Object> candidates=new ArrayList<>();
            if("pile".equals(kind)) {
                List<Object> a=new ArrayList<>(),b=new ArrayList<>();for(Card x:left)a.add(ref(x,d));for(Card x:right)b.add(ref(x,d));
                for(long i=0;i<2;i++)candidates.add(Json.map("candidate_id",900L+i,"semantic",Json.map(
                        "kind","choose_pile","source",null,"purpose","effect","pile_index",i,"piles",Arrays.asList(a,b))));
            } else {
                long i=0;for(String key:effects.keySet())candidates.add(Json.map("candidate_id",900L+i,"semantic",Json.map(
                        "kind","choose_replacement","affected",Json.map("player","p0"),"event","other",
                        "replacement_source",sourced?ref((Card)objects.get(key),d):null,
                        "replacement_index",i++,"replacement_count",(long)effects.size())));
            }
            // Candidate identifiers/order do not substitute for the actual pile or map iterator order.
            Collections.reverse(candidates);d.put("candidates",candidates);return d;
        }
        Object call(Game game) {
            return "pile".equals(kind)?(Object)c.player.choosePile(Outcome.Benefit,"same label",left,right,game)
                    :c.player.chooseReplacementEffect(effects,sourced?objects:null,game);
        }
        Object oracle() {
            JackAmountReplayCheck.Oracle oracle=new JackAmountReplayCheck.Oracle(c.player);
            oracle.admitted=(Game)Proxy.newProxyInstance(Game.class.getClassLoader(),new Class<?>[]{Game.class},(o,m,a)->{
                if("getPlayer".equals(m.getName()) && oracle.getId().equals(a[0]))return oracle;
                try{return m.invoke(c.world.game,a);}catch(InvocationTargetException failure){throw failure.getCause();}
            });
            return "pile".equals(kind)?(Object)oracle.choosePile(Outcome.Benefit,"oracle",left,right,oracle.admitted)
                    :oracle.chooseReplacementEffect(effects,sourced?objects:null,oracle.admitted);
        }
        Map<String,Object> record(boolean prefix,boolean implicit) {
            Map<String,Object> r=c.record(false);r.put("decision",decision());
            if(prefix) {
                Map<String,Object> past=decision(),candidate=Json.obj(Json.arr(past,"candidates").get(Json.arr(past,"candidates").size()-1));
                Json.obj(r,"replay").put("earlier",Collections.singletonList(Json.map("decision",past,"selection",
                        Json.map("candidate_id",candidate.get("candidate_id"),"semantic_echo",candidate.get("semantic")))));
            }
            c.player.activationWork=()->{
                if(implicit) {
                    require(c.player.chooseReplacementEffect(null,null,c.world.game)==0,"null implicit replacement changed");
                    require(c.player.chooseReplacementEffect(Collections.singletonMap("only","label"),null,c.world.game)==0,
                            "single implicit replacement changed");
                }
                if(prefix)call(c.world.game);call(c.world.game);
            };return r;
        }
    }
    public static void main(String[] args) throws Exception {
        List<Object> rows=new ArrayList<>();
        for(String kind:Arrays.asList("pile","replacement"))for(boolean sourced:new boolean[]{false,true})
                for(boolean unordered:new boolean[]{false,true})for(boolean prefix:new boolean[]{false,true})
                for(boolean implicit:new boolean[]{false,true})for(int count:new int[]{2,3,4}) {
            Menu m=new Menu(kind,count,sourced,unordered);Map<String,Object> r=m.record(prefix,implicit);Object expected=m.oracle();
            KitRandom random=JackAmountReplayCheck.random(3);Map<String,Object> result=m.c.control(r).choose();
            Map<String,Object> semantic=Json.obj(Json.obj(result,"selection"),"semantic_echo");
            require("pile".equals(kind)?Boolean.TRUE.equals(expected) && Long.valueOf(0).equals(semantic.get("pile_index"))
                    :Integer.valueOf(0).equals(expected) && Long.valueOf(0).equals(semantic.get("replacement_index")),"inherited parent oracle changed");
            require(m.c.backend.calls==0 && m.c.backend.copies==0 && !m.c.backend.closed
                    && JackAmountReplayCheck.draws(random)==0,"fixed inherited callback consumed scoring/random or closed session");
            require(Long.valueOf(prefix?1:0).equals(result.get("original_dialog_prefix_replayed")),"inherited prefix changed");
            rows.add(Json.map("kind",kind,"sources",sourced,"unordered",unordered,"prefix",prefix,"implicit",implicit,"count",(long)count));
            m.c.registry.close();
        }
        for(String kind:Arrays.asList("pile","replacement"))for(String fault:Arrays.asList(
                "hole","duplicate-id","duplicate-index","fractional-index","foreign-source","viewer","family","historical")) {
            Menu m=new Menu(kind,3,true,false);Map<String,Object> r=m.record("historical".equals(fault),false),d=Json.obj(r,"decision");
            Map<String,Object> candidate=Json.obj(Json.arr(d,"candidates").get(0)),semantic=Json.obj(candidate,"semantic");
            String field="pile".equals(kind)?"pile_index":"replacement_index";
            if("hole".equals(fault))Json.arr(d,"candidates").remove(0);
            if("duplicate-id".equals(fault))candidate.put("candidate_id",Json.obj(Json.arr(d,"candidates").get(1)).get("candidate_id"));
            if("duplicate-index".equals(fault))semantic.put(field,Json.obj(Json.obj(Json.arr(d,"candidates").get(1)),"semantic").get(field));
            if("fractional-index".equals(fault))semantic.put(field,0.5);
            if("foreign-source".equals(fault))Json.obj(d,"context").put("source",Json.map("object_id","hidden"));
            if("viewer".equals(fault))d.put("acting_seat","p1");
            if("family".equals(fault))semantic.put("kind","choose_boolean");
            if("historical".equals(fault)) {
                Map<String,Object> past=Json.obj(Json.arr(Json.obj(r,"replay"),"earlier").get(0));
                Map<String,Object> other=Json.obj(Json.arr(Json.obj(past,"decision"),"candidates").get(0));
                past.put("selection",Json.map("candidate_id",other.get("candidate_id"),"semantic_echo",other.get("semantic")));
            }
            KitRandom random=JackAmountReplayCheck.random(3);refused(()->m.c.control(r).choose());
            require(m.c.backend.calls==0 && m.c.backend.copies==0 && m.c.backend.closed
                    && JackAmountReplayCheck.draws(random)==0,"malformed inherited callback did work or retained session");
        }
        for(String fault:Arrays.asList("pile-order","physical-card","hidden-card","replacement-order","replacement-event","affected","count")) {
            Menu m=new Menu(fault.startsWith("replacement") || "affected".equals(fault) || "count".equals(fault)?"replacement":"pile",3,true,false);
            Map<String,Object> r=m.record(false,false),d=Json.obj(r,"decision");
            Map<String,Object> semantic=Json.obj(Json.obj(Json.arr(d,"candidates").get(0)),"semantic");
            if("pile-order".equals(fault))Collections.reverse(m.left);
            if("physical-card".equals(fault))m.left.set(0,m.right.get(0));
            if("hidden-card".equals(fault))m.left.set(0,new JackDialogReplayCheck.StableCard(m.c.root.other.getId(),"Hidden",9));
            if("replacement-order".equals(fault)) {List<String> keys=new ArrayList<>(m.effects.keySet());Collections.reverse(keys);
                Map<String,String> copy=new LinkedHashMap<>(m.effects);m.effects.clear();for(String key:keys)m.effects.put(key,copy.get(key));}
            if("replacement-event".equals(fault))semantic.put("event","damage");
            if("affected".equals(fault))semantic.put("affected",Json.map("player","p1"));
            if("count".equals(fault))semantic.put("replacement_count",4L);
            refused(()->m.c.control(r).choose());require(m.c.backend.calls==0 && m.c.backend.closed,"mismatched actual menu retained session");
        }
        System.out.println(Json.canonical(rows));
        System.out.println("JackInheritedReplayCheck PASS: unchanged parent pile/replacement oracle, exact physical piles and map iterator order, implicit replacements, valid prefixes and historical disagreement refusal; metadata only, native qualification pending");
    }
}
