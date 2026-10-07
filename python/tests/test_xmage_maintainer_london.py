"""Whole-hand London draws and multi-card bottom selections stay bound."""
import copy
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/"tools"))
import xmage_maintainer_london as london
from xmage_maintainer_selection import GREEDY, MaintainerSelectionSession
from xmage_maintainer_sources import CALLBACK_SHA256, ENCODER_SHA256, LONDON_VARIANT, london_source, stage
from xmage_neural_decisions import decision_hash
from test_xmage_maintainer_inference import Peer
from test_xmage_maintainer_modes import Model, fixture as mode_fixture

SOURCES = {"embedding_cache_sha256":"a"*64,"encoder_source_sha256":ENCODER_SHA256,
           "candidate_source_sha256":CALLBACK_SHA256,"london_rules_source_sha256":"b"*64}

def fixture(count=3):
    start={"seat":"p0","game_id":"london","agent_seed":7}
    hand=[{"object_id":"own-"+str(i),"card_name":"Forest","owner_seat":"p0","zone":"hand"} for i in range(count)]
    k=min(2,count)
    d={"acting_seat":"p0","seat_step":10,"context":{"kind":"choice","rewind":False},
       "group":{"group_id":88,"substep_index":0,"substep_count":k},
       "observation":{"viewer":"p0","phase_step":"pregame","players":[{"seat":"p0","hand":hand,"hand_count":count}]},
       "candidates":[{"candidate_id":20+i,"semantic":{"kind":"order_pick","purpose":"mulligan_bottom","source":None,
                         "position":0,"count":k,"item":{"object":copy.deepcopy(c)}}} for i,c in enumerate(hand)]}
    indices=[0,2,1] if count==3 else [0]
    _,_,_,_,_,features=mode_fixture()
    features=copy.deepcopy(features);features.update(kind="candidates",head="card_select",candidate_mask=[True]*count+[False]*(64-count),
             candidate_ids=list(range(100,100+count))+[0]*(64-count),candidate_features=[[0]*48 for _ in range(64)])
    frame={"id":"1","event":"choose","call":1,"type":"LONDON_MULLIGAN","candidate_count":count,"picks":count,
           "sequential":True,"candidate_refs":[c["object_id"] for c in hand],"features":features,"decision_sha256":decision_hash(d)}
    receipt={key:copy.deepcopy(value) for key,value in frame.items() if key not in ("id","event","features")};receipt["indices"]=indices
    frames = [frame] if count>1 else []
    receipts = [receipt] if count>1 else []
    if count==3:
        second=copy.deepcopy(frame);second.update(call=2,candidate_count=2,picks=2,candidate_refs=["own-0","own-2"])
        second["features"].update(candidate_mask=[True]*2+[False]*62,candidate_ids=[100,102]+[0]*62)
        frames.append(second)
        second_receipt={key:copy.deepcopy(value) for key,value in second.items() if key not in ("id","event","features")}
        second_receipt["indices"]=[0,1];receipts.append(second_receipt)
    req={"id":"1","game_start":start,"decision":d,"world_seed":"1"*64,"id_seed":"2"*64}
    result={"decision_sha256":decision_hash(d),"request_sha256":decision_hash(req),"variant":LONDON_VARIANT,
            "world_flags":[],"neural_calls":len(receipts),"rounds":receipts,
            "bottomed":["own-1","own-2"] if count==3 else ["own-0"]}
    ready={"ready":True,"encoder":"maintainer-permitted-london","embedding_count":4,"original_callback_sha256":CALLBACK_SHA256,
           "variant":LONDON_VARIANT,**SOURCES}
    peer=Peer([ready,*frames,{"id":"1","event":"result","ok":True,"result":result}])
    chooser=Peer([{"ready":True,"selection":"maintainer-original-no-training","profile":GREEDY,"seed":7,"callback_source_sha256":CALLBACK_SHA256},
                  {"id":"1","ok":True,"indices":indices},{"id":"2","ok":True,"indices":[0,1]}])
    model=Model(start);model.encoding["card_embeddings_sha256"]=SOURCES["embedding_cache_sha256"]
    model.score=lambda value,timeout_s:{"probabilities":[1/sum(value["candidate_mask"]) if valid else 0 for valid in value["candidate_mask"]],"value":0.2}
    return start,d,peer,model,chooser,result,frame

def test_whole_hand_draw_and_last_two_targets_bind_each_public_substep():
    start,d,peer,model,chooser,result,frame=fixture()
    session=london.LondonSession(peer,model,MaintainerSelectionSession(chooser,profile=GREEDY,seed=7),game_start=start,sources=SOURCES)
    _,plan=session.plan(d,world_seed="1"*64,id_seed="2"*64,timeout_s=5)
    assert chooser.writes[0]["picks"]==3 and chooser.writes[0]["sequential"] is True
    assert chooser.writes[1]["picks"]==2 and chooser.writes[1]["sequential"] is True
    assert plan.select(d)=={"candidate_id":21,"semantic_echo":d["candidates"][1]["semantic"]}
    next_=copy.deepcopy(d);next_["seat_step"]+=1;next_["group"]["substep_index"]=1
    next_["candidates"]=[c for c in reversed(next_["candidates"]) if c["candidate_id"]!=21]
    for c in next_["candidates"]:c["semantic"]["position"]=1;c["candidate_id"]+=100
    assert plan.select(next_)["candidate_id"]==122 and plan.complete
    session.close();assert peer.closed and chooser.closed and model.closed==1

def test_single_hand_card_bypasses_policy_and_original_rng():
    start,d,peer,model,chooser,result,frame=fixture(1)
    def unexpected(*a,**kw): raise AssertionError("singleton must bypass inference")
    model.score=unexpected
    session=london.LondonSession(peer,model,MaintainerSelectionSession(chooser,profile=GREEDY,seed=7),game_start=start,sources=SOURCES)
    _,plan=session.plan(d,world_seed="1"*64,id_seed="2"*64,timeout_s=5)
    assert plan.select(d)["candidate_id"]==20 and plan.complete and not chooser.writes
    session.close()

@pytest.mark.parametrize("edit",[
    lambda d:d["observation"]["players"][0]["hand"].pop(),
    lambda d:d["candidates"][0]["semantic"].update(purpose="library_bottom"),
    lambda d:d["candidates"][0]["semantic"].update(source={"object_id":"opponent"}),
    lambda d:d["candidates"][0]["semantic"].update(position=True),
    lambda d:d["candidates"][0].update(candidate_id=True),
    lambda d:d["candidates"][0]["semantic"]["item"]["object"].update(card_name="Other Card"),
    lambda d:d["group"].update(substep_index=1),
])
def test_changed_or_hidden_candidate_refuses_before_model(edit):
    start,d,peer,model,chooser,result,frame=fixture();edit(d)
    with pytest.raises(ValueError):
        london.LondonPlan(start,d,result,rounds=result["rounds"],request_hash=result["request_sha256"])

@pytest.mark.parametrize("edit",[
    lambda r:r.update(bottomed=["own-2","own-1"]),
    lambda r:r["rounds"][0].update(indices=[2,1]),
    lambda r:r["rounds"][0].update(indices=[0,1,1]),
    lambda r:r.update(world_flags=["unsupported:unknown"]),
    lambda r:r.update(request_sha256="e"*64),
])
def test_result_must_preserve_full_draw_and_original_last_n_order(edit):
    start,d,peer,model,chooser,result,frame=fixture();edited=copy.deepcopy(result);edit(edited)
    with pytest.raises(ValueError):london.LondonPlan(start,d,edited,rounds=edited["rounds"],request_hash=result["request_sha256"])

def test_london_source_refuses_unknown_private_bytes():
    with pytest.raises(ValueError,match="pinned"):london_source("unknown private callback")

@pytest.mark.parametrize("flag",[1,"true",[],None])
def test_staging_flag_requires_explicit_boolean(tmp_path,flag):
    with pytest.raises(ValueError,match="explicit boolean"):
        stage({"schema":"spellbench-xmage-release-inputs/v1","inference_backends":{"maintainer-rl-april":{"london_callback":flag}}},tmp_path,tmp_path/"new")
