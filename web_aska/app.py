from . import create_app

app = create_app()

if __name__ == "__main__":
    # Note: For local debugging only. Gunicorn will use the 'app' object directly.
    app.run(host='0.0.0.0', port=5001, debug=True)
