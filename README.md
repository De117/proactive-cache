# Proactive cache
A proactive cache always has a cache of fresh tokens, except in two cases:

  - when it's still starting up
  - when an origin server is down

A **token** is the resource we're caching, with a time to live (TTL).
An **origin server** is the server which provides fresh tokens. We don't want
to overload it, hence the cache.
