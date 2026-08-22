import json

from django.http import HttpResponseRedirect, HttpResponseNotFound, JsonResponse
from django.shortcuts import render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator

from .services import create_short_url, resolve_short_url
from .tasks import record_click


def home(request):
    """Simple form-based UI: paste a URL, get a short one back."""
    context = {}
    if request.method == 'POST':
        long_url = request.POST.get('long_url', '').strip()
        try:
            URLValidator()(long_url)
            obj = create_short_url(long_url)
            context['short_url'] = request.build_absolute_uri(f'/{obj.short_code}')
        except ValidationError:
            context['error'] = 'Please enter a valid URL.'
    return render(request, 'shortener/home.html', context)


@method_decorator(csrf_exempt, name='dispatch')
class ShortenAPIView(View):
    """
    POST /api/shorten/  {"long_url": "https://..."}
    -> {"short_code": "21", "short_url": "http://host/21"}

    Kept as a thin wrapper around services.create_short_url -- the view's
    only job is HTTP in/out translation, not business logic.
    """

    def post(self, request):
        try:
            body = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON body'}, status=400)

        long_url = (body.get('long_url') or '').strip()
        if not long_url:
            return JsonResponse({'error': 'long_url is required'}, status=400)

        try:
            URLValidator()(long_url)
        except ValidationError:
            return JsonResponse({'error': 'long_url is not a valid URL'}, status=400)

        obj = create_short_url(long_url)
        return JsonResponse({
            'short_code': obj.short_code,
            'short_url': request.build_absolute_uri(f'/{obj.short_code}'),
            'long_url': obj.long_url,
        }, status=201)


def redirect_short_url(request, short_code):
    """
    GET /<short_code>
    This is THE hot path. Every design decision upstream (indexing,
    caching, async click counting) exists to keep this function fast.
    """
    long_url = resolve_short_url(short_code)
    if long_url is None:
        return HttpResponseNotFound('Short URL not found or expired.')

    # .delay() sends this to the Celery queue and returns IMMEDIATELY --
    # it does not wait for a worker to actually pick it up or run it.
    # The redirect below fires without waiting on the click count at all.
    record_click.delay(short_code)
    return HttpResponseRedirect(long_url)
