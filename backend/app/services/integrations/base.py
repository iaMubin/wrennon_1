from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any

class EcommerceProvider(ABC):
    @abstractmethod
    def get_order_status(self, order_id: str) -> Optional[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def get_order_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    def process_refund(self, order_id: str, amount: float) -> Dict[str, Any]:
        pass

    @abstractmethod
    def update_subscription(self, customer_email: str, action: str) -> Dict[str, Any]:
        pass

    @abstractmethod
    def recommend_product(self, context_keywords: str) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def track_purchase(self, product_id: str) -> Dict[str, Any]:
        pass

class CRMProvider(ABC):
    @abstractmethod
    def create_support_ticket(self, customer_email: str, conversation_summary: str, order_id: Optional[str] = None) -> Dict[str, Any]:
        pass

    @abstractmethod
    def reopen_support_ticket(self, ticket_id: str, conversation_summary: str) -> Dict[str, Any]:
        pass
