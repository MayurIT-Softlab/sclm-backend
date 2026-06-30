from django.http import JsonResponse

def api_health_check(request):
    """
    A simple public endpoint to verify the API is running.
    In a real-world scenario, AWS or Docker pings this URL every minute 
    to make sure our server hasn't crashed.
    """
    return JsonResponse({
        "status": "online",
        "system": "SCLM Enterprise API",
        "message": "Welcome to the Supply Chain & Logistics Management System.",
        "version": "1.0.0"
    }, status=200)