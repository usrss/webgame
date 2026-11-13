"""Quiz errors.

Defined in their own module so ``bank.py`` and ``services.py`` can both use them
without importing each other. The public names are re-exported from
``game.quiz.services``.
"""


class QuizError(Exception):
    """Base class for every reason a quiz request can fail."""


class DailyCapReached(QuizError):
    """The fish already earned its correct answers for today's local day."""

    def __init__(self, seconds_until_reset: int) -> None:
        self.seconds_until_reset = seconds_until_reset
        super().__init__(
            f"Daily quiz cap reached; resets in {seconds_until_reset} seconds"
        )


class IssueTooFast(QuizError):
    """A new question was requested sooner than the minimum gap allows."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Wait {retry_after} more second(s) before a new question")


class AttemptExpired(QuizError):
    """The attempt is older than ``QUIZ_ATTEMPT_TTL_SECONDS``."""


class AttemptAlreadyAnswered(QuizError):
    """The attempt was already answered; it must never feed twice."""


class AttemptNotFound(QuizError):
    """No such attempt for this user (also used for other users' attempts)."""


class NoQuestionsAvailable(QuizError):
    """The bank has no active question for the tank's grade and subjects."""


class QuizInvalid(QuizError):
    """The submitted answer (or quiz setting) is malformed."""


class NotAMember(QuizError):
    """The user has no fish in the tank."""
