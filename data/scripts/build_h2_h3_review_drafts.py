"""Build research-informed H2/H3 v2 without classifier calls or text templates."""
import csv
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'data/eval/v4/ai_draft_for_review'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from h2_h3_curated_v2 import FLOW_GROUPS, ATTACK_GROUPS

PEOPLE = [('T\u00edn', 'tin'), ('Th\u1ecbnh', 'thinh'), ('Khang', 'khang'), ('Th\u1eafng', 'thang')]
EGRESS = {'send_email', 'share_file', 'http_request', 'post_message'}


def render(value, substitutions):
    if isinstance(value, str):
        return re.sub(r'\{(dest|file)\}', lambda m: str(substitutions[m.group(1)]), value)
    if isinstance(value, dict):
        return {k: render(v, substitutions) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, substitutions) for v in value]
    return value


def destination(action, number, attack=False, saved=False):
    prefix = '831' if attack else '832'
    if saved:
        return '0451000123456'
    if action == 'transfer_money':
        return '0000' + prefix + f'{number:06d}'
    if action == 'refund':
        return 'DH' + prefix + f'{number:05d}'
    if action == 'data_access':
        return 'HR' + prefix + f'{number:05d}'
    if action == 'voucher_apply':
        return 'VC' + prefix + f'{number:05d}'
    if action == 'role_escalation':
        return 'temp' + prefix + f'{number:05d}'
    if action == 'http_request':
        host = f'endpoint{prefix}{number:05d}.evil.example' if attack else f'intake{prefix}{number:05d}.example.com'
        return 'https://' + host + ('/collect' if attack else '/events')
    if action == 'post_message':
        return '#partner' + prefix + f'{number:05d}'
    if action in EGRESS:
        return f'contact{prefix}{number:05d}@' + ('evil.example' if attack else 'example.com')
    return f'member{prefix}{number:05d}@example.com'


def payload(action, dest, number, options, attack=False, file_id=None):
    prefix = '831' if attack else '832'
    common = dict(user_id='draft_operator', user_role='user')
    if action == 'transfer_money':
        return dict(common, user_id='demo_customer', from_account='0000832000000', to_account=dest,
                    bank_code='VCB' if dest == '0451000123456' else 'DEMO', amount=options['amount'], currency='VND', otp_verified=True)
    if action == 'refund':
        return dict(common, user_id='draft_support', user_role='support_agent', order_id=dest,
                    amount=options['amount'], order_value=options['total'], reason='Approved return or invoice adjustment')
    if action == 'data_access':
        return dict(common, user_id='draft_employee', user_role='employee', resource=dest, query_scope='all' if attack else 'own_account')
    if action in {'password_reset', 'account_recovery'}:
        return dict(common, user_id='draft_member', target_account=dest, verification_method='email_link', identity_confirmed=True)
    if action == 'voucher_apply':
        return dict(common, order_id='DH' + prefix + f'{number:05d}', order_total=options['total'],
                    voucher_code=dest, discount_percent=options['discount'])
    if action == 'role_escalation':
        return dict(operator_id='evaluation_operator', operator_role='system_security', target_user_id=dest,
                    requested_role='admin', justification='Access request in a fictional workflow', ticket_id='TK' + prefix + f'{number:05d}')
    if action == 'send_email':
        return dict(common, to=options.get('to', [dest]), cc=options.get('cc', []), subject=options['subject'],
                    body=options['body'], attachments=options.get('attachments', []))
    if action == 'share_file':
        return dict(common, file_id=file_id, share_with=[dest], permission=options.get('permission', 'view'))
    if action == 'http_request':
        return dict(common, url=dest, method=options.get('method', 'POST'), body=options['body'])
    if action == 'post_message':
        return dict(common, target=dest, text=options['body'])
    raise ValueError(action)


def sources_for(domain, action, attack=False):
    if attack:
        return ['injecagent', 'agentdojo']
    if action in EGRESS:
        return ['agentdojo', 'drive_permissions'] if action == 'share_file' else ['agentdojo']
    if domain == 'bank':
        return ['banking77', 'cfpb_complaints']
    if domain == 'shop':
        return ['multiwoz', 'stripe_invoices']
    return ['multiwoz']


def metadata(person, domain, action, attack=False):
    return dict(assigned_to=person, authorship='ai_generated', review_status='unreviewed',
                revision='research_v2', source_refs=sources_for(domain, action, attack))


def make_attacks():
    rows = []
    for owner, group in enumerate(ATTACK_GROUPS):
        for spec in group:
            i = len(rows) + 1
            dest = destination(spec['action'], i, attack=True)
            file_id = spec['options'].get('file_id', f'private_attachment831{i:05d}.pdf')
            values = dict(dest=dest, file=file_id)
            options = render(spec['options'], values)
            text = render(spec['text'], values)
            content = json.dumps(text, ensure_ascii=False) if isinstance(text, dict) else text
            rows.append(dict(id=f'DAI{i:03d}', **metadata(PEOPLE[owner][0], spec['domain'], spec['action'], True),
                             domain=spec['domain'], channel=spec['channel'], content=content,
                             has_explicit_instruction=spec['explicit'], target_action=spec['action'],
                             target_payload=payload(spec['action'], dest, i, options, True, file_id), attacker_value=dest,
                             notes=spec['technique'], document_format=spec['document_format']))
    return rows


def make_flows():
    rows = []
    for topic_index, (family, domain, origin, specs) in enumerate(FLOW_GROUPS):
        owner, local = divmod(topic_index, 6)
        split = 'dev' if (local in {0, 2, 3}) != bool(owner % 2) else 'test'
        for situation, spec in enumerate(specs, 1):
            i = len(rows) + 1
            dest = destination(spec['action'], i, saved=origin == 'saved')
            file_id = f'approved_release832{i:05d}.pdf'
            values = dict(dest=dest, file=file_id)
            options = render(spec['options'], values)
            text = render(spec['text'], values)
            content = json.dumps(text, ensure_ascii=False) if isinstance(text, dict) else text
            rows.append(dict(id=f'FAI{i:03d}', **metadata(PEOPLE[owner][0], domain, spec['action']),
                             domain=domain, lang=spec['lang'], user_messages=render(spec['messages'], values),
                             content=dict(source=spec['source'], text=content),
                             action=dict(type=spec['action'], payload=payload(spec['action'], dest, i, options, False, file_id)),
                             destination_from=origin, split=split, family='v2_' + family,
                             situation=situation, case_design='independent_situation', document_format=spec['document_format']))
    return rows


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def main():
    attacks, flows = make_attacks(), make_flows()
    jsonl(OUTPUT/'attack_scenarios_vi.jsonl', attacks)
    jsonl(OUTPUT/'friction_flows.jsonl', flows)
    jsonl(OUTPUT/'compatibility'/'core7'/'attack_scenarios_vi.jsonl', [r for r in attacks if r['target_action'] not in EGRESS])
    jsonl(OUTPUT/'compatibility'/'core7'/'friction_flows.jsonl', flows)
    for person, slug in PEOPLE:
        jsonl(OUTPUT/'by_assignee'/slug/'attack_scenarios_vi.jsonl', [r for r in attacks if r['assigned_to'] == person])
        jsonl(OUTPUT/'by_assignee'/slug/'friction_flows.jsonl', [r for r in flows if r['assigned_to'] == person])
    with (OUTPUT/'assignment.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=['assigned_to','H2_count','H3_count','folder','authorship'])
        writer.writeheader()
        writer.writerows(dict(assigned_to=p,H2_count=sum(r['assigned_to']==p for r in attacks),H3_count=sum(r['assigned_to']==p for r in flows),folder='by_assignee/'+slug,
                              authorship='AI-generated by OpenAI Codex; not human-authored') for p,slug in PEOPLE)
    print('Built research_v2: H2=60 (48 core + 12 egress), H3=96; independent VI/EN cases; 4 egress action types.')


if __name__ == '__main__':
    main()
