package com.demo.ticket;

public class TicketOrder {
    private final String orderId;
    private final String userId;
    private final String showId;
    private final int ticketCount;
    private String status;

    public TicketOrder(String orderId, String userId, String showId, int ticketCount) {
        this.orderId = orderId;
        this.userId = userId;
        this.showId = showId;
        this.ticketCount = ticketCount;
        this.status = "CREATED";
    }

    public String getOrderId() {
        return orderId;
    }

    public String getUserId() {
        return userId;
    }

    public String getShowId() {
        return showId;
    }

    public int getTicketCount() {
        return ticketCount;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }
}
