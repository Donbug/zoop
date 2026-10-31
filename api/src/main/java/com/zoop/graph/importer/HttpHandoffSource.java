package com.zoop.graph.importer;

import java.util.Set;
import java.util.function.Supplier;

import com.zoop.ai.AiClientException;
import com.zoop.ai.AiServiceRejectionException;
import com.zoop.ai.AiTransportException;
import com.zoop.ai.handoff.HandoffReadClient;
import com.zoop.ai.handoff.HandoffReadClient.HandoffRead;
import com.zoop.graph.importer.HandoffExportParser.VerifiedHandoff;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * ai/service's read-only handoff HTTP as the handoff source. {@code GET /internal/v1/graph-handoffs/{id}/bundle} answers with
 * the producer's CURRENT verification of the handoff and, only while it is current and matches the operator's two pins on the
 * AI side, the frozen manifest and the whole bundle; the look right before the commit is the content-free
 * {@code GET /internal/v1/graph-handoffs/{id}} (the same verification without the 6 MiB). This class maps the service's refusals
 * onto the importer's codes and hands the answers to {@link HandoffReadParser}, which re-verifies everything the CLI path
 * verifies.
 * <ul>
 * <li>A withheld answer is {@code handoff_withheld} with the service's reason code (never "no data").</li>
 * <li>503 answers ({@code runtime_busy}, {@code runtime_unavailable}, {@code service_busy}, {@code service_configuration_invalid})
 *     and transport failures (connect, timeout, I/O) are {@code handoff_export_unavailable}: a later run may succeed.</li>
 * <li>An answer outside the contract (malformed or unexpected body, over the size bound, a redirect) is
 *     {@code handoff_export_invalid}: the same request will not do better until the service is fixed.</li>
 * <li>Every other error envelope (401, 403 {@code handoff_not_allowed}, 404 {@code handoff_not_found}, 409
 *     {@code execution_unavailable}, 422, 500 {@code runtime_contract_mismatch}/{@code runtime_binding_mismatch}) is
 *     {@code handoff_refused} with that code: the same request will not do better until an operator acts.</li>
 * </ul>
 */
public final class HttpHandoffSource implements HandoffSource {
    private static final Logger log = LoggerFactory.getLogger(HttpHandoffSource.class);
    private static final Set<AiTransportException.Failure> OUTSIDE_CONTRACT = Set.of(
            AiTransportException.Failure.RESPONSE_MALFORMED, AiTransportException.Failure.UNEXPECTED_RESPONSE,
            AiTransportException.Failure.RESPONSE_TOO_LARGE, AiTransportException.Failure.REDIRECT_REFUSED);
    private final HandoffReadClient client;
    private final HandoffReadParser parser;

    public HttpHandoffSource(HandoffReadClient client) {
        this(client, new HandoffReadParser());
    }

    HttpHandoffSource(HandoffReadClient client, HandoffReadParser parser) {
        this.client = client;
        this.parser = parser;
    }

    @Override
    public VerifiedHandoff fetch(GraphHandoffRequest request) {
        HandoffRead read = answer(() -> client.bundle(request.handoffId()));
        // The per-request stamps are logged, not kept in the receipt (which is a function of the pins).
        log.info("handoff {} read over HTTP: delivery {} checkedAt {} observedAt {}", request.handoffId(), read.delivery().state(),
                read.delivery().checkedAt().orElse("-"), read.observedAt());
        return parser.parse(read, request);
    }

    @Override
    public Current current(GraphHandoffRequest request) {
        return parser.current(answer(() -> client.status(request.handoffId())), request);
    }

    private static HandoffRead answer(Supplier<HandoffRead> route) {
        try {
            return route.get();
        } catch (AiServiceRejectionException refused) {
            if (refused.httpStatus() == 503) {
                throw new GraphHandoffException(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE);
            }
            throw GraphHandoffException.handoffRefused(refused.code());
        } catch (AiTransportException transport) {
            throw new GraphHandoffException(OUTSIDE_CONTRACT.contains(transport.failure())
                    ? GraphHandoffFailure.HANDOFF_EXPORT_INVALID : GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE);
        } catch (AiClientException other) {
            throw new GraphHandoffException(GraphHandoffFailure.HANDOFF_EXPORT_UNAVAILABLE);
        } catch (IllegalArgumentException outsideContract) {
            throw new GraphHandoffException(GraphHandoffFailure.HANDOFF_EXPORT_INVALID);
        }
    }
}
