import json
import re
import shutil
from pathlib import Path

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.authentication import MongoJWTAuthentication
from apps.accounts.rbac import CanViewCatalog, IsMongoAuthenticated

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / 'tf_templates'


def _slugify(text):
    return re.sub(r'[^a-z0-9]+', '_', text.lower().strip()).strip('_')


def _load_template_from_dir(folder: Path):
    for json_path in sorted(folder.glob('*.json')):
        if json_path.name.startswith('.'):
            continue
        with open(json_path) as f:
            data = json.load(f)
        tf_path = json_path.with_suffix('.tf')
        data['_json_path'] = str(json_path)
        data['_tf_path']   = str(tf_path) if tf_path.exists() else None
        data['tfContent']  = tf_path.read_text() if tf_path.exists() else ''
        return data
    return None


def _load_templates():
    templates = []
    for folder in sorted(TEMPLATES_DIR.iterdir()):
        if not folder.is_dir() or folder.name == 'default':
            continue
        t = _load_template_from_dir(folder)
        if t:
            templates.append(t)
    return templates


def _find_template(pk):
    """Return (template_dict, folder_path) or (None, None)."""
    for folder in TEMPLATES_DIR.iterdir():
        if not folder.is_dir() or folder.name == 'default':
            continue
        t = _load_template_from_dir(folder)
        if t and t.get('id') == pk:
            return t, folder
    return None, None


class TemplateListView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [CanViewCatalog]

    def get(self, request):
        templates = _load_templates()
        if category := request.query_params.get('category'):
            templates = [t for t in templates if t.get('category') == category]
        # Strip internal path keys before returning
        for t in templates:
            t.pop('_json_path', None)
            t.pop('_tf_path', None)
        return Response(templates)

    def post(self, request):
        if not request.user.has_permission('manage_templates'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        template_id = data.get('id', '').strip()
        name        = data.get('name', '').strip()
        if not template_id or not name:
            return Response({'detail': 'id and name are required.'}, status=status.HTTP_400_BAD_REQUEST)

        folder = TEMPLATES_DIR / _slugify(template_id)
        if folder.exists():
            return Response({'detail': f'Template folder {folder.name!r} already exists.'}, status=status.HTTP_409_CONFLICT)

        folder.mkdir(parents=True)
        slug = _slugify(template_id)

        meta = {k: v for k, v in data.items() if k not in ('tfContent',)}
        json_path = folder / f'{slug}.json'
        json_path.write_text(json.dumps(meta, indent=2))

        if tf_content := data.get('tfContent', ''):
            (folder / f'{slug}.tf').write_text(tf_content)

        return Response({**meta, 'tfContent': tf_content}, status=status.HTTP_201_CREATED)


class TemplateDetailView(APIView):
    authentication_classes = [MongoJWTAuthentication]
    permission_classes = [IsMongoAuthenticated]

    def get(self, request, pk):
        if not request.user.has_permission('view_catalog'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        t, _ = _find_template(pk)
        if not t:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        t.pop('_json_path', None)
        t.pop('_tf_path', None)
        return Response(t)

    def put(self, request, pk):
        if not request.user.has_permission('manage_templates'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        t, folder = _find_template(pk)
        if not t:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        # Update JSON metadata
        meta = {k: v for k, v in data.items() if k not in ('tfContent', '_json_path', '_tf_path')}
        # Preserve id
        meta['id'] = pk
        json_path = Path(t['_json_path'])
        json_path.write_text(json.dumps(meta, indent=2))

        # Update .tf file
        tf_content = data.get('tfContent', '')
        slug = folder.name
        tf_path = folder / f'{slug}.tf'
        if tf_content:
            tf_path.write_text(tf_content)
        elif tf_path.exists():
            tf_path.unlink()

        return Response({**meta, 'tfContent': tf_content})

    def delete(self, request, pk):
        if not request.user.has_permission('manage_templates'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        t, folder = _find_template(pk)
        if not t:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        shutil.rmtree(folder)
        return Response(status=status.HTTP_204_NO_CONTENT)
