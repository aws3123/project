package com.demo.ticket;

import org.springframework.stereotype.Repository;

@Repository
public class OrderRepository {
    public void save(TicketOrder order) {
    }

    public void markPaid(String orderId) {
    }

    public boolean existsPaidOrder(String userId, String showId) {
        return false;
    }
}
