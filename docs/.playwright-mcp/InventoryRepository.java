package com.demo.ticket;

import org.springframework.stereotype.Repository;

@Repository
public class InventoryRepository {
    public int findRemaining(String showId) {
        return 5;
    }

    public void decrease(String showId, int ticketCount) {
    }

    public void increase(String showId, int ticketCount) {
    }
}
