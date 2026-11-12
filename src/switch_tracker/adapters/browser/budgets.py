"""Shared time budgets for browser collection.

Kept separate from the Playwright-backed adapter so service-level tests and
configuration checks can inspect the budget without importing Playwright.
"""

#: The adapter's OWN time budget, and the reason a long walk is not a data loss.
#:
#: CollectService wraps every store in asyncio.wait_for. When that fires the
#: coroutine is CANCELLED, its local listings list dies with the frame, and the
#: store records `failed` with zero rows -- every page already scraped, thrown
#: away. Nothing can recover them from outside; they only exist in here.
#:
#: So the adapter stops ITSELF first and returns Partial through the normal
#: path, which CollectService persists like any other result. The service's
#: deadline stays as a backstop for an adapter that is genuinely wedged rather
#: than merely slow.
#:
#: Must stay below CollectService.DEFAULT_BROWSER_DEADLINE_S or the self-limit
#: never gets the chance to fire. Asserted by a test rather than by this
#: comment, because a comment cannot fail a build.
DEFAULT_TIME_BUDGET_S = 540.0
