# Proactive cache
A proactive cache always has fresh tokens, except in two cases:

  - when it's still starting up
  - when an origin server is down

A **token** is the resource we're caching, with a time to live (TTL).
An **origin server** is the server which provides fresh tokens. We don't want
to overload it, hence the cache.

The logic can be generalized to cache arbitrary HTTP resources (e.g. with
appropriate `Cache-Control` directives), but the use case I had in mind was
OAuth 2.0 access tokens.


This repository has:
  * a thread-based implementation in `sync`
  * a coroutine-based implementation in `async`
