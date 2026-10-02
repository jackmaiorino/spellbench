"""Recheck the first serial Luna game's selections and recorded host ending.

A request timeout may forfeit that game. Its entire engine prefix, final
offered decision and canonical host adjudication still have to match the
ledger. This check makes no model request and never searches for a better game.
"""
import argparse
import hashlib
import json
from pathlib import Path

from spellbench import wire
from spellbench.arena.ledger import LedgerRow
from spellbench.conformance import _engine_exchanges
from spellbench.digests import GameDigest
from spellbench.host.validator import LiveValidator
from spellbench.messages import Decision, EnvHelloOk, Rules, StepRequest, Terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--traces', type=Path, required=True)
    parser.add_argument('--broker-logs', type=Path, help='required for a recorded request-timeout forfeit')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    ledgers = sorted(args.records.glob('trial-1-workers-1.jsonl'))
    if len(ledgers) != 1:
        raise RuntimeError('exactly one retained serial qualification trial required')
    for line in ledgers[0].read_bytes().splitlines():
        row = LedgerRow.from_json(wire.strict_json_loads(line)).to_json()
        if any(seat['name']=='llm-gpt-6-luna' for seat in row['seats']):
            rows.append(row)
    row = min(rows,key=lambda r:r['game_index'])
    natural = row['classification']=='natural' and row['adjudication'] is None
    timeout_forfeit = (row['classification']=='forfeit' and row['adjudication'] is not None
                       and row['adjudication']['kind']=='forfeit'
                       and row['adjudication']['cause']=='agent_error'
                       and row['reason']=='forfeit:agent_error')
    if not (natural or timeout_forfeit):
        raise RuntimeError('the first serial Luna game needs a natural ending or verified request-timeout forfeit')
    matches = []
    for path in sorted(args.traces.glob('*.transcript.jsonl')):
        exchanges = _engine_exchanges(path)
        resets = [(i,req,answer) for i,(_,req,_,answer) in enumerate(exchanges)
                  if isinstance(req,dict) and req.get('request_type')=='reset']
        if len(resets)==1 and resets[0][1]['game_id']==row['game_id']:
            matches.append((path,exchanges,resets[0]))
    if len(matches)!=1:
        raise RuntimeError('first serial Luna game must have one exact retained engine transcript')
    path,exchanges,(reset_index,reset,response) = matches[0]
    hello = EnvHelloOk.from_json(exchanges[0][3])
    validator = LiveValidator(hello,Rules.from_json(reset['rules']),
                              max_decisions=reset['max_decisions'],max_steps=reset['max_steps'])
    chain = GameDigest(reset)
    chain.add_response(response)
    previous = response
    for _,request,_,answer in exchanges[reset_index+1:]:
        decision = Decision.from_json(previous)
        seat_decision = validator.check(decision)
        step = StepRequest.from_json(request)
        if step.expected_step!=decision.step or step.game_id!=row['game_id']:
            raise RuntimeError('recorded step binding differs from the decision')
        candidate = step.selection.candidate_id
        if not 0<=candidate<len(seat_decision['candidates']):
            raise RuntimeError('recorded selection is outside the legal candidates')
        if wire.canonical_json_dumps(step.selection.semantic_echo)!=wire.canonical_json_dumps(seat_decision['candidates'][candidate]['semantic']):
            raise RuntimeError('recorded selection semantic differs from its legal candidate')
        validator.answered(seat_decision,candidate)
        chain.add_step(request,answer)
        previous = answer
    timeout_binding = None
    if natural:
        terminal = Terminal.from_json(previous)
        validator.check_terminal(terminal)
        if (terminal.result.step_count!=validator.answered_steps
                or terminal.result.decision_count!=validator.completed_groups):
            raise RuntimeError('engine terminal counts differ from the recorded choices')
    else:
        final_decision = Decision.from_json(previous)
        offered = validator.check(final_decision)
        loser = row['adjudication']['loser_seat']
        winner = 'p1' if loser=='p0' else 'p0'
        if (loser!=offered['acting_seat'] or row['winner']!=winner or row['outcome']!=winner+'_win'
                or not any(seat['seat']==loser and seat['name']=='llm-gpt-6-luna' for seat in row['seats'])):
            raise RuntimeError('forfeit is not the Luna seat at the final offered decision')
        if args.broker_logs is None:
            raise RuntimeError('a timeout forfeit requires its retained broker log')
        bindings = []
        for log in sorted(args.broker_logs.glob('broker-*.jsonl')):
            for line in log.read_bytes().splitlines():
                event = wire.strict_json_loads(line)
                if (event.get('event')=='inference' and event.get('game_id')==row['game_id']
                        and event.get('seat_step')==offered['seat_step']):
                    bindings.append((log,event))
        if (len(bindings)!=1 or bindings[0][1].get('status')!='error'
                or bindings[0][1].get('error')!='timeout'
                or bindings[0][1].get('unknown_usage') is not True):
            raise RuntimeError('the final offered decision lacks one exact uncertain timeout record')
        log,event = bindings[0]
        timeout_binding = {'broker_log':str(log.resolve()),
                           'broker_log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
                           'seat_step':offered['seat_step'],'error':'timeout','unknown_usage':True}
        chain.add_adjudication(classification=row['classification'],outcome=row['outcome'],
                               reason=row['reason'],winner=row['winner'])
    if (row['step_count']!=validator.answered_steps
            or row['decision_count']!=validator.completed_groups
            or validator.decisions_checked!=row['decisions_checked']
            or chain.value()!=row['game_digest']):
        raise RuntimeError('recorded choices do not reproduce host counts and the ledger digest')
    receipt = {'kind':'recorded-choice-host-validation','game_index':row['game_index'],
               'game_id':row['game_id'],'game_digest':chain.value(),'decisions_checked':validator.decisions_checked,
               'transcript':str(path.resolve()),'transcript_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
               'serial_ledger_sha256':hashlib.sha256(ledgers[0].read_bytes()).hexdigest(),
               'exchanges':len(exchanges),'passed':True,'model_requests':0,
               'classification':row['classification'],'timeout_binding':timeout_binding,
               'selection_rule':'lowest game_index involving Luna in the first serial trial, fixed before its outcomes',
               'non_claim':'recorded choice validation; no new model outputs or playing-strength claim'}
    args.out.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
