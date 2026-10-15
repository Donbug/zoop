package com.zoop.auth.service;

import java.time.Instant;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.zoop.auth.dto.SignupRequest;
import com.zoop.auth.repository.SignupTermRow;
import com.zoop.auth.repository.SignupTermsRepository;
import com.zoop.common.exception.CustomException;
import com.zoop.common.exception.ErrorCode;
import org.springframework.stereotype.Component;

@Component
public class SignupAgreementPolicy {
    private final SignupTermsRepository repository;

    public SignupAgreementPolicy(SignupTermsRepository repository) {
        this.repository = repository;
    }

    public List<SignupRequest.Agreement> validate(List<SignupRequest.Agreement> submitted, Instant at) {
        if (submitted == null) {
            throw new CustomException(ErrorCode.INVALID_REQUEST);
        }
        List<SignupTermRow> current = repository.listCurrent(at);
        Map<String, SignupTermRow> byId = new HashMap<>();
        for (SignupTermRow term : current) {
            byId.put(term.id(), term);
            if (term.required() && term.version() == null) {
                throw new CustomException(ErrorCode.TERMS_REQUIRED);
            }
        }
        if (current.stream().noneMatch(SignupTermRow::required)) {
            throw new CustomException(ErrorCode.TERMS_REQUIRED);
        }

        Set<String> seen = new HashSet<>();
        for (SignupRequest.Agreement agreement : submitted) {
            if (agreement == null || agreement.id() == null || agreement.version() == null
                    || agreement.accepted() == null || !seen.add(agreement.id())) {
                throw new CustomException(ErrorCode.INVALID_REQUEST);
            }
            SignupTermRow term = byId.get(agreement.id());
            if (term == null) {
                throw new CustomException(ErrorCode.INVALID_REQUEST);
            }
            if (term.version() == null || !term.version().equals(agreement.version())
                    || term.required() && !agreement.accepted()) {
                throw new CustomException(ErrorCode.TERMS_REQUIRED);
            }
        }
        for (SignupTermRow term : current) {
            if (term.required() && !seen.contains(term.id())) {
                throw new CustomException(ErrorCode.TERMS_REQUIRED);
            }
        }
        return List.copyOf(submitted);
    }
}
