# Addressing GitHub recent availability issues

来源: https://github.blog/news-insights/company-news/addressing-githubs-recent-availability-issues-2/

抓取日期: 2026-09-16

Addressing GitHub’s recent availability issues - The GitHub Blog

Vlad Fedorov·@v-fedorov-gh

March 11, 2026

|
 
 7 minutes

Share:

Over the past several weeks, GitHub has experienced significant availability and performance issues affecting multiple services. Three of the most significant incidents happened on February 2, February 9, and March 5.

First and foremost, we take responsibility. We have not met our own availability standards, and we know that reliability is foundational to the work you do every day. We understand the impact these outages have had on your teams, your workflows, and your confidence in our platform.

Here, we’ll unpack what’s been causing these incidents and what we’re doing to make our systems more resilient moving forward.

What happened

These incidents have occurred during a period of extremely rapid usage growth across our platform, exposing scaling limitations in parts of our current architecture. Specifically, we’ve found that recent platform instability was primarily driven by rapid load growth, architectural coupling that allowed localized issues to cascade across critical services, and inability of the system to adequately shed load from misbehaving clients.

Before we cover what we are doing to prevent these issues going forward, it is worth diving into the details of the most impactful incidents.

February 9 incident

On Monday, February 9, we experienced a high‑impact incident due to a core database cluster that supports authentication and user management becoming overloaded. The mistakes that led to the problem were made days and weeks earlier.

In early February, two very popular client-side applications that make a significant amount of API calls against our servers were released, with unintentional changes driving a more-than-tenfold increase in read traffic they generated. Because these applications end up being updated by the users over time, the increase in usage doesn’t become evident right away; it appears as enough users upgrade.

On Saturday, February 7, we deployed a new model. While trying to get it to customers as quickly as possible, we changed a refresh TTL on a cache storing user settings from 12 to 2 hours. The model was released to a narrower set of customers due to limited capacity, which made the change necessary. At this point, everything was operating normally because the weekend load is significantly lower, and we didn’t have sufficiently granular alarms to detect the looming issue.

Three things then compounded on February 9: our regular peak load, many customers updating to the new version of the client apps as they were starting their week, and another new model release. At this point, the write volume due to the increased TTL and the read volume from the client apps combined to overwhelm the database cluster. While the TTL change was quickly identified as a culprit, it took much longer to understand why the read load kept increasing, which prolonged the incident. Further, due to the interaction between different services after the database cluster became overwhelmed, we needed to block the extra load further up the stack, and we didn’t have sufficiently granular switches to identify which traffic we needed to block at that level.

The investigation for the February 9 incident raised a lot of important questions about why the user settings were stored in this particular database cluster and in this particular way. The architecture was originally selected for simplicity at a time when there were very few models and very few governance controls and policies related to those models. But over time, something that was a few bytes per user grew into kilobytes. We didn’t catch how dangerous that was because the load was visible only during new model or policy rollouts and was masked by the TTL. Since this database cluster houses data for authentication and user management, any services that depend on these were impacted.

GitHub Actions incidents on February 2 and March 5

We also had two significant instances where our failover solution was either insufficient or didn’t function correctly:

Actions hosted runners had a significant outage on February 2. Most cloud infrastructure issues in this area typically do not cause impact as they occur in a limited number of regions, and we automatically shift traffic to healthy regions. However, in this case, there was a cascading set of events triggered by a telemetry gap that caused existing security policies to be applied to key internal storage accounts affecting all regions. This blocked access to VM metadata on VM creates and halted hosted runner lifecycle operations.

Another impactful incident for Actions occurred on March 5. Automated failover has been progressively rolling out across our Redis infrastructure, and on this day, a failover occurred for a Redis cluster used by Actions job orchestration. The failover performed as expected, but a latent configuration issue meant the failover left the cluster in a state with no writable primary. With writes failing and failover not available as a mitigation, we had to correct the state manually to mitigate. This was not an aggressive rollout or missing resiliency mechanism, but rather latent configuration that was only exposed by an event in production infrastructure.

For both of these incidents, the investigations brought up unexpected single points of failure that we needed to protect and needed to dry run failover procedures in the production more rigorously.

Across these incidents, contributing factors expanded the scope of impact to be much broader or longer than necessary, including:

Insufficient isolation between critical path components in our architecture

Inadequate safeguards for load shedding and throttling

Gaps in end-to-end validation, monitoring for attention on earlier signals, and partner coordination during incident response

What we are doing now

Our engineering teams are fully engaged in both near-term mitigations and durable longer-term architecture and process investments. We are addressing two common themes: managing rapidly increasing load by focusing on resilience and isolation of critical paths and preventing localized failures from ever causing broad service degradation.

In the near term, we are prioritizing stabilization work to reduce the likelihood and impact of incidents. This includes:

Redesigning our user cache system, which hosts model policies and more, to accommodate significantly higher volume in a segmented database cluster.

Expediting capacity planning and completing a full audit of fundamental health for critical data and compute infrastructure to address urgent growth.

Further isolate key dependencies so that critical systems like GitHub Actions and Git will not be impacted by any shared infrastructure issues, reducing cascade risk. This is being done through a combination of removing or handling dependency failures where possible or isolating dependencies.

Protecting downstream components during spikes to prevent cascading failures while prioritizing critical traffic loads.

In parallel, we are accelerating deeper platform investments to deliver on GitHub’s commitment to supporting sustained, high-rate growth with high availability. These include:

Migrating our infrastructure to Azure to accommodate rapid growth, enabling both vertical scaling within regions and horizontal scaling across regions. In the short term, this provides a hybrid approach for infrastructure resiliency. As of today, 12.5% of all GitHub traffic is served from our Azure Central US region, and we are on track to serving 50% of all GitHub traffic by July. Longer term, this enables simplification of our infrastructure architecture and more global resiliency by adopting managed services.

Breaking apart the monolith into more isolated services and data domains as appropriate, so we can scale independently, enable more isolated change management, and implement localized decisions about shedding traffic when needed.

We are also continuing tactical repair work from every incident.

Our commitment to transparency

We recognize that it’s important to provide you with clear communication and transparency when something goes wrong. We publish summaries of all incidents that result in degraded performance of GitHub services on our status page and in our monthly availability reports. The February report will publish later today with a detailed explanation of incidents that occurred last month, and our March report will publish in April.

Given the scope of recent incidents, we felt it was important to address them with the community today. We know GitHub is critical digital infrastructure, and we are taking urgent action to ensure our platform is available when and where you need it. Thank you for your patience as we strengthen the stability and resilience of the GitHub platform.

Written by

Vladimir Fedorov is GitHub's Chief Technology Officer, bringing decades of experience in engineering leadership and innovation. A passionate advocate for developer productivity, Vlad is leading GitHub’s engineering team to shape the future of developer tools and innovation with a developer-first mindset.

Before joining GitHub, Vlad co-founded UserClouds, a startup specializing in data governance and privacy. He spent 12 years at Facebook, now Meta, as Senior Vice President, leading engineering teams of over 2,000 across Privacy, Ads, and Platform. Earlier in his career, Vlad worked at Microsoft and earned both his BS and MS in Computer Science from Caltech. He currently serves on the board of Codepath.org, an organization dedicated to reprogramming higher education to create the first AI-native generation of engineers, CTOs, and founders.

Vlad lives in the Bay Area and when not working enjoys spending time outside and on the water with his family.

Related posts

Company news

GitHub availability report: August 2026

In August, we experienced five incidents that resulted in degraded performance across GitHub services.

Company news

The August 17 outage, and the work ahead

An update on the August 17 outage and the steps we’re taking to improve reliability.

Company news

Your guide to GitHub Universe 2026 is here: The schedule just launched!

The GitHub Universe session catalog is live. Explore interactive workshops, community talks, demos, and panels. Plus, register before August 19 to save $300.

We do newsletters, too

Discover tips, technical guides, and best practices in our biweekly newsletter just for devs.

Your email address

*
 Your email address

Subscribe

Yes please, I’d like GitHub and affiliates to use my information for personalized communications, targeted advertising and campaign effectiveness. See the GitHub Privacy Statement for more details.

Subscribe
