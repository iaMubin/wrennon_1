import time
import uuid
import json
from locust import HttpUser, task, between

class CustomerUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self):
        self.session_id = str(uuid.uuid4())
        
    @task
    def check_status(self):
        self.client.get(f"/chat/{self.session_id}/status")
        
    @task
    def load_history(self):
        self.client.get(f"/chat/{self.session_id}/history")
