import os
import requests
import json

# Can't hit Anthropic directly without API key. Wait, pi agent doesn't have a configured API key for Anthropic by default. Let's see if we can use the local agent's connection.
