import json
import os

log_file = r'C:\Users\mayur\.gemini\antigravity-ide\brain\04a79603-f333-43e6-8dfc-5c326e72a428\.system_generated\logs\transcript.jsonl'
targets = ['apps\\\\inventory\\\\models.py', 'apps\\\\forecasting\\\\models.py', 'apps\\\\procurement\\\\models.py']
results = {}

with open(log_file, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            data = json.loads(line)
            if 'tool_calls' in data:
                for call in data['tool_calls']:
                    if call['name'] == 'write_to_file' and 'TargetFile' in call['args']:
                        tf = call['args']['TargetFile']
                        for t in targets:
                            if t in tf:
                                raw_content = call['args']['CodeContent']
                                if raw_content.startswith('\"'):
                                    try:
                                        raw_content = json.loads(raw_content)
                                    except Exception:
                                        pass
                                results[t] = raw_content
        except Exception:
            pass

for t, content in results.items():
    out_path = 'c:\\\\IT_Softlab\\\\sclm\\\\sclm_backend\\\\' + t.replace('\\\\', '\\')
    print('Writing to', out_path)
    with open(out_path, 'w', encoding='utf-8') as out:
        out.write(content)
