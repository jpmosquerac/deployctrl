"""
Terraform HTTP backend views.

Terraform is configured with:
    backend "http" {
      address        = "<base>/api/terraform/state/<req-id>/"
      lock_address   = "<base>/api/terraform/state/<req-id>/lock/"
      unlock_address = "<base>/api/terraform/state/<req-id>/lock/"
      lock_method    = "POST"
      unlock_method  = "DELETE"
      username       = "deployctrl"
      password       = "<TF_STATE_SECRET>"
    }

Endpoints
---------
GET    /api/terraform/state/<req-id>/       → return state (200) or empty (204)
POST   /api/terraform/state/<req-id>/       → save state
DELETE /api/terraform/state/<req-id>/       → clear state

POST   /api/terraform/state/<req-id>/lock/  → acquire lock (423 if already locked)
DELETE /api/terraform/state/<req-id>/lock/  → release lock
"""
import base64
import json
from datetime import datetime

from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import TerraformState


def _check_auth(request):
    auth = request.META.get('HTTP_AUTHORIZATION', '')
    if not auth.startswith('Basic '):
        return False
    try:
        _, encoded = auth.split(' ', 1)
        username, password = base64.b64decode(encoded).decode().split(':', 1)
        secret = getattr(settings, 'TF_STATE_SECRET', '')
        return bool(secret) and username == 'deployctrl' and password == secret
    except Exception:
        return False


@method_decorator(csrf_exempt, name='dispatch')
class TerraformStateView(View):

    def _state(self, req_id):
        return TerraformState.objects(req_id=req_id).first()

    def get(self, request, req_id):
        if not _check_auth(request):
            return HttpResponse('Unauthorized', status=401)
        state = self._state(req_id)
        if not state or not state.state_json:
            return HttpResponse(status=204)
        return HttpResponse(state.state_json, content_type='application/json')

    def post(self, request, req_id):
        if not _check_auth(request):
            return HttpResponse('Unauthorized', status=401)
        state = self._state(req_id) or TerraformState(req_id=req_id)
        # Reject if locked by a different run
        lock_id_param = request.GET.get('ID', '')
        if state.lock_id and state.lock_id != lock_id_param:
            return HttpResponse(state.lock_info, status=423, content_type='application/json')
        state.state_json = request.body.decode()
        state.updated_at = datetime.utcnow()
        state.save()
        return HttpResponse(status=200)

    def delete(self, request, req_id):
        if not _check_auth(request):
            return HttpResponse('Unauthorized', status=401)
        state = self._state(req_id)
        if state:
            state.state_json = ''
            state.updated_at = datetime.utcnow()
            state.save()
        return HttpResponse(status=200)


@method_decorator(csrf_exempt, name='dispatch')
class TerraformStateLockView(View):

    def _get_or_create(self, req_id):
        state = TerraformState.objects(req_id=req_id).first()
        if not state:
            state = TerraformState(req_id=req_id)
            state.save()
        return state

    def post(self, request, req_id):
        if not _check_auth(request):
            return HttpResponse('Unauthorized', status=401)
        state = self._get_or_create(req_id)
        if state.lock_id:
            return HttpResponse(state.lock_info, status=423, content_type='application/json')
        lock_info_raw = request.body.decode()
        try:
            lock_id = json.loads(lock_info_raw).get('ID', '')
        except Exception:
            lock_id = ''
        state.lock_id   = lock_id
        state.lock_info = lock_info_raw
        state.save()
        return HttpResponse(lock_info_raw, content_type='application/json')

    def delete(self, request, req_id):
        if not _check_auth(request):
            return HttpResponse('Unauthorized', status=401)
        state = TerraformState.objects(req_id=req_id).first()
        if state:
            state.lock_id   = ''
            state.lock_info = ''
            state.save()
        return HttpResponse(status=200)
