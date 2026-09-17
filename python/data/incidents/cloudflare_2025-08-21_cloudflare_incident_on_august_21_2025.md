# Cloudflare incident on August 21, 2025

来源: https://blog.cloudflare.com/cloudflare-incident-on-august-21-2025/

抓取日期: 2026-09-16

Cloudflare incident on August 21, 2025 | Cloudflare Blog

Skip to content

On August 21, 2025, an influx of traffic directed toward clients hosted in the Amazon Web Services (AWS) us-east-1 facility caused severe congestion on links between Cloudflare and AWS us-east-1. This impacted many users who were connecting to or receiving connections from Cloudflare via servers in AWS us-east-1 in the form of high latency, packet loss, and failures to origins.

Customers with origins in AWS us-east-1 began experiencing impact at 16:27 UTC. The impact was substantially reduced by 19:38 UTC, with intermittent latency increases continuing until 20:18 UTC.

This was a regional problem between Cloudflare and AWS us-east-1, and global Cloudflare services were not affected. The degradation in performance was limited to traffic between Cloudflare and AWS us-east-1. The incident was a result of a surge of traffic from a single customer that overloaded Cloudflare's links with AWS us-east-1. It was a network congestion event, not an attack or a BGP hijack.

We’re very sorry for this incident. In this post, we explain what the failure was, why it occurred, and what we’re doing to make sure this doesn’t happen again.

Background

Cloudflare helps anyone to build, connect, protect, and accelerate their websites on the Internet. Most customers host their websites on origin servers that Cloudflare does not operate. To make their sites fast and secure, they put Cloudflare in front as a reverse proxy.

When a visitor requests a page, Cloudflare will first inspect the request. If the content is already cached on Cloudflare’s global network, or if the customer has configured Cloudflare to serve the content directly, Cloudflare will respond immediately, delivering the content without contacting the origin. If the content cannot be served from cache, we fetch it from the origin, serve it to the visitor, and cache it along the way (if it is eligible). The next time someone requests that same content, we can serve it directly from cache instead of making another round trip to the origin server.

When Cloudflare responds to a request with the cached content, it will send the response traffic over internal Data Center Interconnect (DCI) links through a series of network equipment and eventually reach the routers that represent our network edge (our “edge routers”) as shown below:

Our internal network capacity is designed to be larger than the available traffic demand in a location to account for failures of redundant links, failover from other locations, traffic engineering within or between networks, or even traffic surges from users. The majority of Cloudflare’s network links were operating normally, but some edge router links to an AWS peering switch had insufficient capacity to handle this particular surge.

What happened

At approximately 16:27 UTC on August, 21, 2025, a customer started sending many requests from AWS us-east-1 to Cloudflare for objects in Cloudflare’s cache. These requests generated a volume of response traffic that saturated all available direct peering connections between Cloudflare and AWS. This initial saturation became worse when AWS, in an effort to alleviate the congestion, withdrew some BGP advertisements to Cloudflare over some of the congested links. This action rerouted traffic to an additional set of peering links connected to Cloudflare via an offsite network interconnection switch, which subsequently also became saturated, leading to significant performance degradation. The impact became worse for two reasons: One of the direct peering links was operating at half-capacity due to a pre-existing failure, and the Data Center Interconnect (DCI) that connected Cloudflare’s edge routers to the offsite switch was due for a capacity upgrade. The diagram below illustrates this using approximate capacity estimates:

In response, our incident team immediately engaged with our partners at AWS to address the issue. Through close collaboration, we successfully alleviated the congestion and fully restored services for all affected customers.

Timeline

Time

Description

2025-08-21 16:27 UTC

Traffic surge for single customer begins, doubling total traffic from Cloudflare to AWSIMPACT START

2025-08-21 16:37 UTC

AWS begins withdrawing prefixes from Cloudflare on congested PNI (Private Network Interconnect) BGP sessions

2025-08-21 16:44 UTC

Network team is alerted to internal congestion in Ashburn (IAD)

2025-08-21 16:45 UTC

Network team is evaluating options for response, but AWS prefixes are unavailable on paths that are not congested due to their withdrawals

2025-08-21 17:22 UTC

AWS BGP prefixes withdrawals result in a higher amount of dropped trafficIMPACT INCREASE

2025-08-21 17:45 UTC

Incident is raised for customer impact in Ashburn (IAD)

2025-08-21 19:05 UTC

Rate limiting of single customer causing traffic surge decreases congestion

2025-08-21 19:27 UTC

Network team additional traffic engineering actions fully resolve congestionIMPACT DECREASE

2025-08-21 19:45 UTC

AWS begins reverting BGP withdrawals as requested by Cloudflare

2025-08-21 20:07 UTC

AWS finishes normalizing BGP prefix announcements to Cloudflare over IAD PNIs

2025-08-21 20:18 UTC

IMPACT END

When impact started, we saw a significant amount of traffic related to one customer, resulting in congestion:

This was handled by manual traffic actions both from Cloudflare and AWS. You can see some of the attempts by AWS to alleviate the congestion by looking at the number of IP prefixes AWS is advertising to Cloudflare during the duration of the outage. The lines in different colors correspond to the number of prefixes advertised per BGP session with us. The dips indicate AWS attempting to mitigate by withdrawing prefixes from the BGP sessions in an attempt to steer traffic elsewhere:

The congestion in the network caused network queues on the routers to grow significantly and begin dropping packets. Our edge routers were dropping high priority packets consistently during the outage, as seen in the chart below, which shows the queue drops for our Ashburn routers during the impact period:

The primary impact to customers as a result of this congestion would have been latency, loss (timeouts), or low throughput. We have a set of latency Service Level Objectives defined which imitate customer requests back to their origins measuring availability and latency. We can see that during the impact period, the percentage of requests whose latency fails to meet the target SLO threshold dips below an acceptable level in lock step with the packet drops during the outage:

After the congestion was alleviated, there was a brief period where both AWS and Cloudflare were attempting to normalize the prefix advertisements that had been adjusted to attempt to mitigate the congestion. That caused a long tail of latency that may have impacted some customers, which is why you see the packet drops resolve before the customer latencies are restored.

Remediations and follow-up steps

This event has underscored the need for enhanced safeguards to ensure that one customer's usage patterns cannot negatively affect the broader ecosystem. Our key takeaways are the necessity of architecting for better customer isolation to prevent any single entity from monopolizing shared resources and impacting the stability of the platform for others, and augmenting our network infrastructure to have sufficient capacity to meet demand.

To prevent a recurrence of this issue, we are implementing a multi-phased mitigation strategy. In the short and medium term:

We are developing a mechanism to selectively deprioritize a customer’s traffic if it begins to congest the network to a degree that impacts others.

We are expediting the Data Center Interconnect (DCI) upgrades which will provide network capacity significantly above what it is today.

We are working with AWS to make sure their and our BGP traffic engineering actions do not conflict with one another in the future.

Looking further ahead, our long-term solution involves building a new, enhanced traffic management system. This system will allot network resources on a per-customer basis, creating a budget that, once exceeded, will prevent a customer's traffic from degrading the service for anyone else on the platform. This system will also allow us to automate many of the manual actions that were taken to attempt to remediate the congestion seen during this incident.

Conclusion

Customers accessing AWS us-east-1 through Cloudflare experienced an outage due to insufficient network congestion management during an unusual high-traffic event.

We are sorry for the disruption this incident caused for our customers. We are actively making these improvements to ensure improved stability moving forward and to prevent this problem from happening again.

Related tags

OutagePost Mortem

Follow on Social Media

Cloudflare

David Tuber

Bryton Herdes

Subscribe to receive notifications of new posts

Email address

We’ll never share your email address.

Subscribe

Thanks for subscribing! Check your inbox to confirm.

Search is temporarily unavailable.

Login opens in a new tabDashboard opens in a new tabContact Sales opens in a new tabStart Building opens in a new tab

opens in a new tab opens in a new tab opens in a new tab

All Categories

AI

Developers

Radar

Product News

Security

Policy & Legal

Zero Trust

Speed & Reliability

Life at Cloudflare

Partners

English

Switch Site Language

English

Deutsch

Español

Español (Latinoamérica)

Français

Italiano

日本語

한국어

繁體中文

简体中文

Português

Русский

Bahasa Indonesia

ภาษาไทย

Tiếng Việt

Polski

العربية

עברית

Svenska

Nederlands

Türkçe

LightDark
