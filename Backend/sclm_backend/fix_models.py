import os
import ast

targets = [
    r'c:\IT_Softlab\sclm\sclm_backend\apps\inventory\models.py',
    r'c:\IT_Softlab\sclm\sclm_backend\apps\forecasting\models.py',
    r'c:\IT_Softlab\sclm\sclm_backend\apps\procurement\models.py'
]

for t in targets:
    with open(t, 'r', encoding='utf-8') as f:
        content = f.read()
    
    if content.startswith('"'):
        try:
            content = ast.literal_eval(content)
        except Exception as e:
            print('Failed to parse', t, e)
            continue
            
    with open(t, 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed', t)
