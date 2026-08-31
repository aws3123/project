---
source: vercel
title: "Vercel service disruption on October 20, 2025"
url: https://vercel.com/blog/update-regarding-vercel-service-disruption-on-october-20-2025
date: 2025-10-20
---

# Update regarding Vercel service disruption on October 20, 2025

**Published:** October 21, 2025 | **Authors:** Guillermo Rauch, Malte Ubl, Matthew Binshtok

---

At Vercel, our philosophy is to *take ownership for*, not blame, our vendors. Customers use our services to gain velocity, reliability, and ship wonderful products. Whether we picked A or B as one of the components of our “circuit design” is entirely our responsibility.

Vercel is fully accountable for this incident, even if it's [now public](https://www.cnn.com/business/live-news/amazon-tech-outage-10-20-25-intl) that it was triggered by the unexpected outage of AWS `us-east-1` (called `iad1` [region](https://vercel.com/docs/regions#region-list)). Vercel uses AWS [infrastructure primitives](https://vercel.com/blog/behind-the-scenes-of-vercels-infrastructure), is part of the [AWS marketplace](https://vercel.com/blog/vercel-and-aws-partner-on-ai-tools-and-experiences), offers [secure connectivity](https://vercel.com/changelog/vpc-peering-now-available-as-self-service-for-vercel-secure-compute) to AWS services, and shares a long history with AWS of [pioneering serverless computing](https://vercel.com/blog/aws-and-vercel-accelerating-innovation-with-serverless-computing).

To our customers, Vercel is **unequivocally responsible for this outage**.

Our goal is to [simplify](https://rauchg.com/2025/the-ai-cloud) the cloud and offer its best version. Through [framework-defined infrastructure](https://vercel.com/blog/framework-defined-infrastructure), we help developers focus on the application layer by deploying global infrastructure resources that are highly optimized. We operate our Compute, CDN, and Firewall services across 19 AWS regions, terminating and securing traffic in 95 cities and 130+ global points of presence.

Yesterday, we fell short of this promise. While a significant amount of traffic [was still served](https://x.com/rauchg/status/1980314641613091318), and we shielded customers from the exposure to a single global point of failure, our ambition is to **enable customers to never drop a single request, **even in the event of an outage.

## Service disruption overview

The AWS outage caused 2 independent incidents on the Vercel side.

The first incident, caused by the initial loss of the `us-east-1` data center, led to temporary disruption of Vercel’s serving of customers' production traffic.

The second incident, caused by an outage of our feature flag provider as a cascading failure of the `us-east-1` outage, had no impact on serving production traffic, but did cause a major disruption of Vercel’s control plane which impacted the Vercel dashboard, APIs, builds and log processing.

### Initial loss of the `us-east-1` region

Vercel’s stack for serving production traffic is designed to survive loss of any one of our 19 regions of operation. We have demonstrated this capability many times in the past, but Monday’s incident caused an unexpected cascading failure leading to additional impact.

![In red: Impact of primary outage on global traffic.](//images.ctfassets.net/e5382hct74si/1fwg4OU0AGSfgHBCzjl13F/6e3850e513f4e8cfd2aea17e48b76f46/AWSOuttage-blog-light.png)
*In red: Impact of primary outage on global traffic.*

Our team was first alerted of initial issues at 06:55 UTC. At first, we only observed minor disruption of traffic. Out of abundance of caution, the team began re-routing traffic away from `us-east-1` at 07:15 UTC, restoring serving for end users connecting directly to that region.

At 07:25 UTC we began rerouting function invocations for customers with [configured backup or secondary regions](https://vercel.com/docs/functions/configuring-functions/region), restoring their full service.

At 07:45 UTC a cascading failure led to a loss of a percentage of our global caching infrastructure leading to failures of static file serving peaking at about 22% of traffic. This period was the largest impact throughout the event. Service was restored at 08:18 UTC. We have already mitigated the root cause of this cascading failure.

![The yellow line shows elevated errors in function invocations during the outage window.](//images.ctfassets.net/e5382hct74si/puhLYWi5q5FLbWrlCjv7F/db44cd38dbabb5f7b33aa039d4c12dc2/AWSOuttage-blog-2-light.png)
*The yellow line shows elevated errors in function invocations during the outage window.*

For customers who do not have multiple function regions configured and who use `us-east-1` as their only region, function invocations were restored at 09:21 UTC

### Secondary disruption of Vercel’s control plane

Vercel's control plane uses `us-west-1` as its primary region and was respectively not directly impacted by the `us-east-1` outage. However, at 19:20 UTC a feature flag provider used by Vercel’s control plane had a major outage likely caused by downstream effects of the earlier `us-east-1` disruption.

Vercel’s control plane is used by Vercel’s dashboard, CLI, API, and services such as log forwarding. This is an entirely independent system of Vercel’s serving stack and hence this disruption had no impact on serving production traffic for our customers. However, it did lead to customers being unable to deploy, initiate rollbacks, and perform other administrative tasks.

The unavailability of the feature flag provider caused an exhaustion of resources in our primary Kubernetes cluster and delayed or caused failures of processing.

At 19:48 UTC the team began to experiment with and then incrementally roll out a mitigation for the unavailability of the feature flag provider and the code pattern leading to resource exhaustion. Full restoration of control plane services occurred around 03:00 UTC.

For additional details and service-specific information, [see the full timeline](#incident-timeline).

## The disruption from the perspective of a request

To provide additional background, in this section we explain the service disruption from the perspective of a request based on the example of a request to [`rauchg.com`](http://rauchg.com):

1. **A DNS lookup is made to ****`rauchg.com`**** to resolve the ****`A`**** record **

- This domain uses Vercel DNS, which leverages anycasted, intelligent DNS and real-time steering to route to healthy endpoints, isolating regional failures for global reliability.
- ✓ This worked as expected.

2. **The DNS query returns a Vercel CDN IP **

- Vercel CDN provides global acceleration via Anycast. A single IP can globally steer traffic to the nearest healthy CDN edge region, minimizing latency, isolating faults, and sustaining reliability across continents.
- While providing Anycast IPs, we still make the recommendation that customers use `CNAME` records, especially when not using Vercel DNS. A `CNAME` provides Vercel’s infrastructure teams with another traffic-steering point for dynamic updates.
- ✓ This worked as expected.

3. **Our L3-L5 protections secure your traffic **

- The Vercel Edge Network provides always-on, managed DDoS protection with automatic detection, adaptive mitigations, and global edge defense. This includes mitigating SYN, UDP, ICMP, TCP floods, malformed and oversized packets, etc.
- ✓ This worked as expected.

4. **A TLS handshake is made to ****`https://rauchg.com`**

- Vercel’s Edge Network contains a global component internally called “HTTPS Terminator”. On a given week, Vercel serves tens of millions of unique domains, which require a sophisticated global replication, storage, and caching system for certificates.
- This system is designed to actively replicate. When a certificate is created, it’s pushed to all our CDN edge regions. When a certificate is read by HTTPS Terminator nodes, it’s cached for performance and fault tolerance reasons.
- ✓ This worked as expected.

5. **Our L7 Firewall secures your traffic **

- Vercel Firewall is a globally distributed service that can protect each region without global dependencies or single points of failure, powered by a component [internally called Protectd](https://vercel.com/blog/protectd-evolving-vercels-always-on-denial-of-service-mitigations). By minimizing its need for global coordination, it has industry-leading L7 mitigation speeds (crucial given the on-demand nature of cloud resource and AI token consumption).
- ✓ This worked as expected.

6. **An HTTP request is made to ****`https://rauchg.com`**

- Vercel CDN has [globally replicated metadata infrastructure](https://x.com/rauchg/status/1979612793478533508) with no single-point-of-failure. This allows us to decode `rauchg.com` into the specific deployment destination. Unlike other services, Vercel typically acts *as both CDN and Origin*, even though each can be used independently.
- The deployment metadata system is one of the most critical parts of our infrastructure, to which we’ve devoted extensive engineering, load testing, failover design.
- ◑ Global deployment metadata worked as expected globally, but if customers hit the `iad1` region directly they saw disruption until we re-routed the `iad1` region.

7. **Once the Vercel CDN obtains deployment metadata, it performs routing.**

- Each Vercel CDN region operates a component internally named Regional Cache. It’s responsible for caching static assets and cacheable dynamic requests. This system is replicated and has strict durability and latency guarantees. The origin of Routing Metadata is `us-east-1` S3, but the system is designed to persist data globally upon first use.
- ✗ While metadata is actively propagated into every region, we experienced a cascading failure of the regional cache service, leading to a wider scope of disruption.

8. **Routing can decide on a number of fates for the request **

- Routing Middleware execution 
  - Customers can use Fluid compute to run logic in the request serving path for dynamic routing and content management, with the full power of the Node.js runtime. This operates as Vercel Functions that are deployed to every CDN Region.
  - ◑ There was initial disruption for users hitting the `us-east-1` region directly, but given the global deployment of Routing Middleware total impact was limited.
- Function invocation 
  - ◑ No impact for customers who did not use `us-east-1` as their only region. For customers who are using `us-east-1` (`iad1`) we performed failover to the backup region if configured.
- Serving HTTP `Cache-Control` content 
  - If a given URL has previously been served and the origin or Function returned `Cache-Control`, Vercel will keep its response in a component internally called Response Cache.
  - ✓ This worked as expected.
- Serving static and ISR content
  - If routing maps a URL to static assets or ISR, it is served from an in-region cache falling back to origin if needed
  - ◑ ISR content continues serving as expected when cached at the edge. For ISR content with `us-east-1` as the origin, there was temporary disruption if the content was not yet cached at the edge.

## Incident timeline

**Monday, October 20, 2025**

`06:55 UTC`: First automated alerts fire for errors across Vercel services, and incidents are automatically created. On-call engineers are paged.

`06:56 UTC`: The primary on-call engineer responds and begins the investigation.

`06:59 UTC`: The primary on-call engineer continues to be paged by additional alerts, and escalates to other on-call engineers for help triaging. An incident call is started to organize the triage.

`07:07 UTC`: On-call engineers determine that there is likely a major issue with AWS-managed services, and they escalate further to the “Panic Rotation”, which pages all of the most senior, experienced on-call responders at Vercel.

`07:15 UTC`: Due to failures in our serving stack, we decide to re-route traffic away from `iad1` into neighboring data centers. We start incrementally re-routing traffic from `iad1` at `07:20 UTC` and the process is complete by 07:44 UTC.

`07:35 UTC`: Due to failures provisioning new build machines in the data center, we decide to re-route builds to another region and complete the process by `07:40 UTC`. At this time, builds with dependencies on resources such as databases outside of Vercel tied to AWS `us-east-1` continue to fail.

`08:16 UTC`: We observe increased failures loading the Vercel Dashboard, and elevated error rates in the Vercel Teams API. The root cause is determined as elevated request latency to external dependencies, which led to CPU starvation. We manually scale up the service at `08:51 UTC`.

`09:15 UTC`: The Vercel Teams API recovers, and we see no more errors loading the Vercel Dashboard.

`09:45 UTC`: New Vercel Deployments using Routing Middleware or Vercel Functions with `iad1` as the selected region are failing due to AWS API issues in the `us-east-1` region. This includes all projects configured with Secure Compute with `iad1` as the specified region.

`10:22 UTC`: We observe health checks passing in the `iad1` builds cluster, and route Secure Compute builds to the cluster. This restores Secure Compute builds.

`11:52 UTC`: We restore service functionality for APIs that create Vercel Functions and Middleware in the `iad1` region.

`17:19 UTC`: We observe a small increase in failures to invoke Vercel Functions in the `iad1` region, and are simultaneously paged for failures scheduling new instances of our Functions routing services.

`17:24 UTC`: We determine the scheduling failures are caused by continued EC2 capacity issues in AWS `us-east-1`. We reduce provisioning for non-critical infrastructure in `iad1` to free capacity for our Functions routing services and observe recovery in invoking Vercel Functions.

`17:29 UTC`: We update the configuration for our serving stack to prefer other regions when serving Vercel Functions (if available) instead of `iad1`.

`17:35 UTC`: We observe decreased errors invoking Vercel Functions in `iad1`. Invocation errors continue at a much lower rate until recovery at `17:49 UTC`.

`17:47 UTC`: Another degradation of AWS APIs leads to build failures caused by errors creating Vercel Functions and Middleware in `iad1`.

`18:50 UTC`: The service backing Vercel Runtime Logs begins experiencing timeouts.

`19:20 UTC`: We begin to observe failures loading the Vercel Dashboard and elevated error responses from Vercel API services. Containers running Vercel Control Plane services, which power the Vercel Dashboard and APIs, begin restarting aggressively.

`19:31 UTC`: Automated alerts for elevated errors in Vercel APIs page the primary on-call engineer. A separate incident is opened to triage this issue.

`19:41 UTC`: We determine timeouts to Vercel’s feature flag provider are the underlying issue in Vercel API services returning 500 responses and the containers restarting.

`19:48 UTC`: We release a change to reduce timeouts and mitigate impact of failed requests to the flag provider. This reduces container restarts, but Vercel API services remain degraded.

`21:20 UTC`: We release an experimental change to degraded services in incremental batches. After observing recovery in the first release, we roll the change to all control plane degraded services by `22:31 UTC`.

**Tuesday, October 21, 2025**

`00:20 UTC`: Vercel Dashboard and API degradation resumes as the flags provider issue recurs. The experimental change from hours earlier had not landed in 100% of services.

`00:48 UTC`: We observe missing Vercel Runtime Logs in several regions. The underlying infrastructure indicates a subset of regions have backlogs of 5-6 hours. We merge a change to increase throughput on these regions.

`02:37 UTC`: All flags clients across Vercel Control Plane services are reconfigured to use the experimental fix.

`03:01 UTC`: Another fix for the logs pipeline is released, and this one successfully unblocks log processing. The backlog age begins to decrease across affected regions.

`03:30 UTC`: The Vercel Dashboard and API services fully recover.

`06:21 UTC`: Runtime Logs fully recover.

## Future improvements

We’re currently working on a highly detailed technical postmortem that will result in systematic mitigation of failure modes discovered by these service disruptions. Additionally, we will continue and intensify our efforts to [rehearse major regional disruptions.](https://vercel.com/blog/preparing-for-the-worst-our-core-database-failover-test)

---

**More posts:** [View all blog posts](https://vercel.com/blog/sitemap.md) | [Changelog](https://vercel.com/changelog/sitemap.md)