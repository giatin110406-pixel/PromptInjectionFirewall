from agent.llm import ScriptedToolLLM
from agent.loop import Agent
from agent.attachments import parse_attachment
from agent.llm import get_tool_llm


def test_successful_refund_has_receipt_and_before_after_values():
    llm = ScriptedToolLLM([{'tool': 'refund', 'arguments': {'order_id': 'DH20261031', 'amount': 30}}, 'done'])
    agent = Agent(llm=llm, mode='off'); agent.reset('refund', 'shop')
    result = agent.run('refund', 'refund')
    step = next(s for s in result.steps if s['kind'] == 'tool_action')
    receipt = result.backend_state['transactions'][0]
    assert step['execution']['ok'] and step['execution']['transaction_id'] == receipt['id']
    assert receipt['status'] == 'executed' and receipt['changes'][0]['before'] == 0 and receipt['changes'][0]['after'] == 30
    assert result.backend_state['initial_state']['orders']['DH20261031']['refunded'] == 0


def test_backend_refusal_has_failed_receipt_and_never_claims_execution():
    llm = ScriptedToolLLM([{'tool': 'transfer_money', 'arguments': {
        'to_account': '0451000123456', 'bank_code': 'VCB', 'amount': 300_000_000}}, 'done'])
    agent = Agent(llm=llm, mode='off'); agent.reset('poor', 'bank')
    result = agent.run('poor', 'transfer')
    step = next(s for s in result.steps if s['kind'] == 'tool_action')
    assert step['decision'] == 'ALLOW' and step['execution']['ok'] is False
    assert result.backend_state['transactions'][0]['status'] == 'failed'
    assert not result.executed and not result.backend_state['transactions'][0]['changes']
    assert result.backend_state['balances']['0071000555666'] == 200_000_000


def test_scripted_fallback_reads_attached_tool_json_by_generated_resource_id():
    agent = Agent(llm=get_tool_llm('scripted', domain='shop'), mode='off'); agent.reset('tool-file', 'shop')
    item = parse_attachment('order.json', b'{"order_id":"DH20261031","amount":30}')
    item['channel'] = 'tool_json'; agent.attach('tool-file', [item])
    result = agent.run('tool-file', 'Tóm tắt kết quả tra cứu giúp mình.')
    read = next(s for s in result.steps if s['kind'] == 'tool_read')
    assert read['tool'] == 'lookup_order' and read['attachment']['id'].startswith('tool-')


def test_approval_is_distinct_from_failed_execution_and_failure_is_counted_once():
    agent = Agent(mode='off'); session = agent.reset('approval', 'bank')
    payload = {'from_account': '0071000555666', 'to_account': '0451000123456', 'amount': 300_000_000}
    session.pending['review-1'] = {'action': 'transfer_money', 'payload': payload, 'review_by': 'user'}
    session.backend.record_decision('transfer_money', payload, 'pending', 'awaiting user', 'review-1')
    out = agent.confirm('approval', 'review-1', True)
    ledger = out['backend_state']['transactions']
    assert out['status'] == 'approved' and not out['executed']
    assert [t['status'] for t in ledger] == ['approved', 'failed']
    assert ledger[0]['execution_ok'] is False and ledger[0]['execution_id'] == ledger[1]['id']
