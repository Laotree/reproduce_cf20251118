# Benchmark Test for Accessing Customer Sites

Evenly access the following URLs:

> [FL with bot manager off](http://127.0.0.1:50001/) 
> [FL with bot manager on](http://127.0.0.1:50002/) 
> [FL2](http://127.0.0.1:50003/) 

## Count the number of successful requests and the number of requests blocked by proxy engines

A request is considered successful when the response status is HTTP 200 and the response body does not contain the string **“bot”**. Otherwise, it is considered blocked by the proxy engines.

For each site, send **10 requests per second**, with a **100 ms timeout**.
Calculate the success rate **every 100 requests**.

## Compare the success rate before and after the failure occurs

Execute the ClickHouse permission change statement that triggers the issue and observe the change in success rate.
