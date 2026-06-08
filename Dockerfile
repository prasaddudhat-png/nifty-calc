# Use official lightweight Python image
FROM python:3.10-slim

# Set working directory inside the container
WORKDIR /app

# Copy the entire workspace (frontend HTML files and backend folder)
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r nifty-calc-backend/requirements.txt

# Move working directory to the backend folder
WORKDIR /app/nifty-calc-backend

# Run uvicorn server (which serves both backend endpoints and frontend HTML)
CMD ["sh", "-c", "uvicorn calc:app --host 0.0.0.0 --port ${PORT:-8000}"]


