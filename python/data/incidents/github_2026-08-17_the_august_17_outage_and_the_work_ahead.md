# The August 17 outage and the work ahead

来源: https://github.blog/news-insights/company-news/the-august-17-outage-and-the-work-ahead/

抓取日期: 2026-09-16

The August 17 outage, and the work ahead - The GitHub Blog

Vlad Fedorov·@v-fedorov-gh

August 20, 2026

|
 
 4 minutes

Share:

On August 17, GitHub experienced an outage that lasted 7 hours and 47 minutes. It disrupted github.com, authentication, GitHub Actions, APIs, pull requests, issues, and Copilot, affecting developers and organizations around the world. If you were trying to ship software that day, we let you down.

This was our second significant incident in August, following an actions failure on August 6. In March and April, I shared the work underway to improve GitHub’s reliability. We have made progress, but these incidents make clear that we must accelerate this work.

What happened

Our investigation found that the outage began when traffic reached a new peak, and a critical infrastructure component in our Central US data center failed to scale with it. The resulting capacity pressure spread through our systems, causing authentication failures and disrupting multiple GitHub services.

Recovery required several coordinated actions. Teams rerouted traffic, isolated affected infrastructure, and restored services in stages. Most GitHub services recovered earlier that day, but some Copilot services took longer. Errors in those services triggered a client-side retry loop that increased traffic during recovery. We had to mitigate that behavior before we could safely restore traffic. The full root cause analysis includes a detailed technical timeline.

Neither outage was caused by a code or configuration change. Both incidents were capacity failures at their core. We failed to scale critical components before demand exceeded their capacity. Since April, monthly commits have grown from 1.4 billion to 2.9 billion. That growth explains the pressure on our systems, but it does not excuse these outages.

What we have done and what comes next

As part of the reliability commitments we made earlier this year, we have focused on three priorities: adding capacity, improving efficiency, and removing architectural bottlenecks. We have since added more than 3 million CPU cores, 120 petabytes of high-speed storage, and significant network capacity. We installed as much hardware as available power allowed in our existing data centers while accelerating our migration to Azure.

Today, Azure serves roughly 58% of GitHub’s platform load and half of all Git operations, up from 12% of platform load in May. This expanded footprint has also supported the growth in GitHub Actions job runs shown below.

Azure’s infrastructure and capacity have also accelerated our work to scale the largest monorepos. Our next milestone is an architecture that scales read capacity linearly with the number of readers, enabling unlimited read operations. We will roll it out gradually, beginning with the largest monorepos.

Scale is not our only challenge. As the pace and complexity of change increased, our existing operational practices did not keep up. We have redirected teams and resources toward availability and invested in stronger testing, safer rollouts, better observability, and more effective alerting. We have made progress, but this work is not complete.

In addition, we are also isolating critical systems and removing shared dependencies between them. This work is designed to reduce the likelihood of an outage and limit its impact when one occurs.

We learn from every outage and add new work to our availability workstream. The August 6 and August 17 incidents led to two immediate changes. First, we are applying consistent retry limits, retry budgets, and variable timeouts across service-to-service interactions to prevent retry storms and cascading load. Second, we are reviewing lower-priority CPU and memory alerts to identify components that could fail during sudden traffic spikes.

Our commitment to high availability isn’t just a technical promise. The developer community depends on GitHub to build, ship, and operate their work. That is only possible if you can rely on us, and on August 17, you couldn’t. It is our responsibility to fix that. We’ll earn your trust through the scaling and reliability of the platform.

Written by

Vladimir Fedorov is GitHub's Chief Technology Officer, bringing decades of experience in engineering leadership and innovation. A passionate advocate for developer productivity, Vlad is leading GitHub’s engineering team to shape the future of developer tools and innovation with a developer-first mindset.

Before joining GitHub, Vlad co-founded UserClouds, a startup specializing in data governance and privacy. He spent 12 years at Facebook, now Meta, as Senior Vice President, leading engineering teams of over 2,000 across Privacy, Ads, and Platform. Earlier in his career, Vlad worked at Microsoft and earned both his BS and MS in Computer Science from Caltech. He currently serves on the board of Codepath.org, an organization dedicated to reprogramming higher education to create the first AI-native generation of engineers, CTOs, and founders.

Vlad lives in the Bay Area and when not working enjoys spending time outside and on the water with his family.

Related posts

Company news

GitHub availability report: August 2026

In August, we experienced five incidents that resulted in degraded performance across GitHub services.

Company news

Your guide to GitHub Universe 2026 is here: The schedule just launched!

The GitHub Universe session catalog is live. Explore interactive workshops, community talks, demos, and panels. Plus, register before August 19 to save $300.

Company news

GitHub availability report: July 2026

In July, we experienced eight incidents that resulted in degraded performance across GitHub services.

We do newsletters, too

Discover tips, technical guides, and best practices in our biweekly newsletter just for devs.

Your email address

*
 Your email address

Subscribe

Yes please, I’d like GitHub and affiliates to use my information for personalized communications, targeted advertising and campaign effectiveness. See the GitHub Privacy Statement for more details.

Subscribe
