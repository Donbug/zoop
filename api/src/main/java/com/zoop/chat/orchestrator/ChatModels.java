package com.zoop.chat.orchestrator;

import com.zoop.chat.dto.Citation;
import com.zoop.chat.executor.ChatRun;
import java.util.List;
import java.util.Set;

/**
 * The model stages the orchestrator calls, as typed ports (design summary 3): the router (Jev), the answer generator (Luna
 * {@code answer-generator}) and the semantic verifier (Jev {@code semantic-verification}). Each is called at most once per
 * run, only after {@code ChatRunControl.beforeModelCall()}. None of them sees a tool, a member id or a database: they get
 * structured input and return typed output the server checks.
 *
 * <p>The production adapter is {@code com.zoop.chat.model.ChatModelStages}; the engine is registered only with
 * {@code zoop.ai.chat-client.enabled=true}, and question intake stays off without it.
 */
public final class ChatModels {
    private ChatModels() {
    }

    /** Jev router: the question chain and its frozen selection → requirements with typed probabilities. */
    public interface Router {
        ChatRouteDecision route(ChatRun run, Set<String> boundCapabilities);
    }

    /** Luna answer generator: answers the answerable requirements of the run from their branch context. */
    public interface Generator {
        ChatGeneratedAnswer generate(ChatRun run, ChatBranchContext context);
    }

    /** Jev semantic verification of the sections that passed the deterministic checks. */
    public interface Verifier {
        ChatSemanticVerdicts verify(ChatRun run, List<ChatGeneratedAnswer.Section> sections, List<Citation> citations);
    }

    /**
     * A model stage failed. {@code fate} says whether the provider may have processed the request: {@link Fate#NOT_SENT}
     * (nothing sent, or a confirmed refusal or malformed answer) may be rerun; {@link Fate#UNKNOWN} (sent, then timed out or
     * disconnected) never is, because the provider may have processed and charged it; {@link Fate#REFUSED} (a policy or
     * configuration refusal: no source grant, the live gate closed, the call budget spent) is not rerun because the same run
     * would be refused again.
     */
    public static final class Failure extends RuntimeException {
        public enum Fate { NOT_SENT, UNKNOWN, REFUSED }

        private final Fate fate;

        public Failure(Fate fate, String message) {
            super(message);
            this.fate = fate;
        }

        public Fate fate() {
            return fate;
        }
    }
}
