import win32com.client
app = win32com.client.GetActiveObject('Photoshop.Application')
for i in range(app.Documents.Count):
    try: app.Documents[i].Close(2)
    except: pass

doc = app.Open(r'C:\PSA\test.psd')
from psa_utils import get_so_psb_name, enter_smart_object

def find_so_by_psb(container, target):
    try:
        layers = container.Layers
    except: return None
    for i in range(layers.Count):
        try:
            lyr = layers[i]
            if getattr(lyr,'Kind',None)==17:
                if get_so_psb_name(app,lyr)==target: return lyr
            r = find_so_by_psb(lyr,target)
            if r: return r
        except: pass
    return None

def dump(container, depth=0):
    try:
        layers = container.Layers
    except: return
    for i in range(layers.Count):
        try:
            lyr = layers[i]
            kind = getattr(lyr,'Kind',None)
            psb = get_so_psb_name(app,lyr) if kind==17 else ''
            print(' '*depth + f'[{kind}] {lyr.Name!r}  psb={psb!r}')
            dump(lyr, depth+2)
        except: pass

input_so = find_so_by_psb(doc, 'Input.psb')
print('Input SO:', input_so.Name if input_so else None)
if input_so:
    so_doc = enter_smart_object(app, input_so)
    print('=== Inside Input.psb ===')
    dump(so_doc)
    so_doc.Close(2)

doc.Close(2)
