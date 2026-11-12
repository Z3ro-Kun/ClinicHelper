"""Conservative comparisons: no model can clear a flag or approve a case."""
from app.models import CaseInput


def normalize(value):
    return ' '.join((value or '').casefold().split())


def reconcile(case: CaseInput):
    flags = []

    def flag(kind, path, left=None, right=None):
        flags.append(dict(id=str(len(flags) + 1), kind=kind, path=path,
                          left=left, right=right, status='open'))

    documents = [case.summary, case.prescription]
    for doc in documents:
        for index, region in enumerate(doc.unreadable_regions):
            flag('unreadable', f'{doc.document_id}.regions.{index}', region.model_dump())
        for index, med in enumerate(doc.medicines):
            for field in ('name', 'dose', 'frequency', 'duration'):
                item = getattr(med, field)
                if item.status != 'present':
                    flag(item.status, f'{doc.document_id}.medicines.{index}.{field}', item.model_dump())
        for group in ('follow_up', 'warning_signs'):
            for index, item in enumerate(getattr(doc, group)):
                if item.status != 'present':
                    flag(item.status, f'{doc.document_id}.{group}.{index}', item.model_dump())

    def indexed(doc):
        result = {}
        for med in doc.medicines:
            if med.name.status != 'present':
                continue
            key = normalize(med.name.value)
            if key in result:
                flag('duplicate', f'{doc.document_id}.medicines.{key}')
            else:
                result[key] = med
        return result

    left, right = map(indexed, documents)
    for key in sorted(left.keys() | right.keys()):
        if key not in left or key not in right:
            flag('missing_item', f'medicines.{key}',
                 left[key].model_dump() if key in left else None,
                 right[key].model_dump() if key in right else None)
            continue
        for field in ('dose', 'frequency', 'duration'):
            a, b = getattr(left[key], field), getattr(right[key], field)
            if a.status == b.status == 'present' and normalize(a.value) != normalize(b.value):
                flag('conflict', f'medicines.{key}.{field}', a.model_dump(), b.model_dump())
    for group in ('follow_up', 'warning_signs'):
        a = {normalize(f.value) for f in getattr(case.summary, group) if f.status == 'present'}
        b = {normalize(f.value) for f in getattr(case.prescription, group) if f.status == 'present'}
        if a != b:
            flag('review_difference', group, sorted(a), sorted(b))
        if not a and not b:
            flag('missing', group)
    return flags
