package com.zoop.graph.read;

import com.zoop.common.request.RequestIdFilter;
import com.zoop.graph.read.dto.GraphResponse;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** OpenAPI {@code getGraph}. {@code personalFilter} only applies to personal mode and is ignored for {@code all}. */
@RestController
@RequestMapping("/api/v1/graph")
public class GraphController {
    private final GraphQueryService service;

    public GraphController(GraphQueryService service) {
        this.service = service;
    }

    @GetMapping
    public GraphResponse getGraph(@RequestParam(required = false) String mode,
            @RequestParam(required = false) String companyId,
            @RequestParam(required = false) Integer depth,
            @RequestParam(required = false) String round,
            @RequestParam(required = false) String graphVersion,
            @RequestParam(required = false) String asOf,
            HttpServletRequest request) {
        return service.getGraph(mode, companyId, depth, round, graphVersion, asOf, RequestIdFilter.currentId(request));
    }
}
