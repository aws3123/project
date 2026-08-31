package com.acme.review.dto;

import java.util.List;
import lombok.Getter;
import lombok.Setter;

@Getter
@Setter
public class TaskListResponse {
    private List<TaskDetailResponse.TaskInfo> items;
    private long total;
    private int page;
    private int size;
    private int totalPages;

    public static TaskListResponse of(List<TaskDetailResponse.TaskInfo> items, long total, int page, int size) {
        TaskListResponse response = new TaskListResponse();
        response.setItems(items);
        response.setTotal(total);
        response.setPage(page);
        response.setSize(size);
        response.setTotalPages((int) Math.ceil((double) total / size));
        return response;
    }
}
