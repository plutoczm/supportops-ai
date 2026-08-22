# SupportOps AI Demo Scenario

## Scenario: Refund Request

### User

> I want to refund order SO-20260801.

### Agent workflow

```text
User request
    |
Identity verification
    |
Intent classification
    |
Order lookup
    |
Refund policy evaluation
    |
Risk assessment
    |
Create pending refund action
    |
Authenticated confirmation
    |
Execute mutation
    |
Write audit record
```

## Safety behavior

The Agent does not directly execute sensitive operations from natural language.

Before mutation:

- customer identity must be verified;
- refund policy must pass;
- high-risk requests require human review;
- confirmation is required;
- action execution uses an idempotency key.

## Knowledge QA scenario

### User

> How long does a refund normally take?

### Retrieval path

```text
Query
 |
BM25 retrieval
 |
Dense retrieval
 |
RRF fusion
 |
Reranking
 |
Answerability gate
 |
Citation-grounded response
```

## Evaluation coverage

The E2E suite evaluates:

- workflow/tool selection;
- task completion;
- tool arguments;
- citation consistency;
- hallucinated actions;
- confirmation safety;
- cross-customer isolation.
