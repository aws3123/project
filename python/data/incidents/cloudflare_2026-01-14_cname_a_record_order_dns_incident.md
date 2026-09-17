# CNAME/A record order DNS incident

来源: https://blog.cloudflare.com/cname-a-record-order-dns-standards/

抓取日期: 2026-09-16

What came first- the CNAME or the A record | Cloudflare Blog

Skip to content

On January 8, 2026, a routine update to 1.1.1.1 aimed at reducing memory usage accidentally triggered a wave of DNS resolution failures for users across the Internet. The root cause wasn't an attack or an outage, but a subtle shift in the order of records within our DNS responses.

While most modern software treats the order of records in DNS responses as irrelevant, we discovered that some implementations expect CNAME records to appear before everything else. When that order changed, resolution started failing. This post explores the code change that caused the shift, why it broke specific DNS clients, and the 40-year-old protocol ambiguity that makes the "correct" order of a DNS response difficult to define.

Timeline

All timestamps referenced are in Coordinated Universal Time (UTC).

Time

Description

2025-12-02

The record reordering is introduced to the 1.1.1.1 codebase

2025-12-10

The change is released to our testing environment

2026-01-07 23:48

A global release containing the change starts

2026-01-08 17:40

The release reaches 90% of servers

2026-01-08 18:19

Incident is declared

2026-01-08 18:27

The release is reverted

2026-01-08 19:55

Revert is completed. Impact ends

What happened?

While making some improvements to lower the memory usage of our cache implementation, we introduced a subtle change to CNAME record ordering. The change was introduced on December 2, 2025, released to our testing environment on December 10, and began deployment on January 7, 2026.

How DNS CNAME chains work

When you query for a domain like www.example.com, you might get a CNAME (Canonical Name) record which indicates one name is an alias for another name. It’s the job of public resolvers, such as 1.1.1.1, to follow this chain of aliases until it reaches a final response:

www.example.com → cdn.example.com → server.cdn-provider.com → 198.51.100.1

As 1.1.1.1 traverses this chain, it caches every intermediate record. Each record in the chain has its own TTL (Time-To-Live), indicating how long we can cache it. Not all the TTLs in a CNAME chain need to be the same:

www.example.com → cdn.example.com (TTL: 3600 seconds) # Still cached

cdn.example.com → 198.51.100.1    (TTL: 300 seconds)  # Expired

When one or more records in a CNAME chain expire, it’s considered partially expired. Fortunately, since parts of the chain are still in our cache, we don’t have to resolve the entire CNAME chain again — only the part that has expired. In our example above, we would take the still valid www.example.com → cdn.example.com chain, and only resolve the expired cdn.example.com A record. Once that’s done, we combine the existing CNAME chain and the newly resolved records into a single response.

The logic change

The code that merges these two chains is where the change occurred. Previously, the code would create a new list, insert the existing CNAME chain, and then append the new records:

impl

 PartialChain

 {

    /// Merges records to the cache entry to make the cached records complete.

    pub

 fn

 fill_cache

(

&

self

, entry

:

 &mut

 CacheEntry

) {

        let

 mut

 answer_rrs 

=

 Vec

::

with_capacity

(entry

.

answer

.

len

() 

+

 self

.

records

.

len

());

        answer_rrs

.

extend_from_slice

(

&

self

.

records); 

// CNAMEs first

        answer_rrs

.

extend_from_slice

(

&

entry

.

answer); 

// Then A/AAAA records

        entry

.

answer 

=

 answer_rrs;

    }

}

However, to save some memory allocations and copies, the code was changed to instead append the CNAMEs to the existing answer list:

impl

 PartialChain

 {

    /// Merges records to the cache entry to make the cached records complete.

    pub

 fn

 fill_cache

(

&

self

, entry

:

 &mut

 CacheEntry

) {

        entry

.

answer

.

extend

(

self

.

records); 

// CNAMEs last

    }

}

As a result, the responses that 1.1.1.1 returned now sometimes had the CNAME records appearing at the bottom, after the final resolved answer.

Why this caused impact

When DNS clients receive a response with a CNAME chain in the answer section, they also need to follow this chain to find out that www.example.com points to 198.51.100.1. Some DNS client implementations handle this by keeping track of the expected name for the records as they’re iterated sequentially. When a CNAME is encountered, the expected name is updated:

;; 

QUESTION

 SECTION

:

;; www

.

example

.

com

.

        IN

    A

;; 

ANSWER

 SECTION

:

www

.

example

.

com

.

    3600

   IN

    CNAME

  cdn

.

example

.

com

.

cdn

.

example

.

com

.

    300

    IN

    A

      198.51

.

100.1

Find records for www.example.com

Encounter www.example.com. CNAME cdn.example.com

Find records for cdn.example.com

Encounter cdn.example.com. A 198.51.100.1

When the CNAME suddenly appears at the bottom, this no longer works:

;; 

QUESTION

 SECTION

:

;; www

.

example

.

com

.

	       IN

    A

;; 

ANSWER

 SECTION

:

cdn

.

example

.

com

.

    300

    IN

    A

      198.51

.

100.1

www

.

example

.

com

.

    3600

   IN

    CNAME

  cdn

.

example

.

com

.

Find records for www.example.com

Ignore cdn.example.com. A 198.51.100.1 as it doesn’t match the expected name

Encounter www.example.com. CNAME cdn.example.com

Find records for cdn.example.com

No more records are present, so the response is considered empty

One such implementation that broke is the getaddrinfo function in glibc, which is commonly used on Linux for DNS resolution. When looking at its getanswer_r implementation, we can indeed see it expects to find the CNAME records before any answers:

for

 (; ancount 

>

 0

; 

--

ancount)

  {

    // ... parsing DNS records ...

    

    if

 (rr.rtype 

==

 T_CNAME)

      {

        /* Record the CNAME target as the new expected name. */

        int

 n 

=

 __ns_name_unpack

 (c.begin, c.end, rr.rdata,

                                  name_buffer, 

sizeof

 (name_buffer));

        expected_name 

=

 name_buffer;

  // Update what we're looking for

      }

    else

 if

 (rr.rtype 

==

 qtype

             &&

 __ns_samebinaryname

 (rr.rname, expected_name)

  // Must match!

             &&

 rr.rdlength 

==

 rrtype_to_rdata_length

 (type:qtype))

      {

        /* Address record matches - store it */

        ptrlist_add

 (list:addresses, item:(

char

 *

) 

alloc_buffer_next

 (abuf, 

uint32_t

));

        alloc_buffer_copy_bytes

 (buf:abuf, src:rr.rdata, size:rr.rdlength);

      }

  }

Another notable affected implementation was the DNSC process in three models of Cisco ethernet switches. In the case where switches had been configured to use 1.1.1.1 these switches experienced spontaneous reboot loops when they received a response containing the reordered CNAMEs. Cisco has published a service document describing the issue.

Not all implementations break

Most DNS clients don’t have this issue. For example, systemd-resolved first parses the records into an ordered set:

typedef

 struct

 DnsAnswerItem

 {

        DnsResourceRecord 

*

rr;

 // The actual record

        DnsAnswerFlags flags;

  // Which section it came from

        // ... other metadata

} 

DnsAnswerItem

;

typedef

 struct

 DnsAnswer

 {

        unsigned

 n_ref;

        OrderedSet 

*

items;

} 

DnsAnswer

;

When following a CNAME chain it can then search the entire answer set, even if the CNAME records don’t appear at the top.

What the RFC says

RFC 1034, published in 1987, defines much of the behavior of the DNS protocol, and should give us an answer on whether the order of CNAME records matters. Section 4.3.1 contains the following text:

If recursive service is requested and available, the recursive response to a query will be one of the following:

- The answer to the query, possibly preface by one or more CNAME RRs that specify aliases encountered on the way to an answer.

While "possibly preface" can be interpreted as a requirement for CNAME records to appear before everything else, it does not use normative key words, such as MUST and SHOULD that modern RFCs use to express requirements. This isn’t a flaw in RFC 1034, but simply a result of its age. RFC 2119, which standardized these key words, was published in 1997, 10 years after RFC 1034.

In our case, we did originally implement the specification so that CNAMEs appear first. However, we did not have any tests asserting the behavior remains consistent due to the ambiguous language in the RFC.

The subtle distinction: RRsets vs RRs in message sections

To understand why this ambiguity exists, we need to understand a subtle but important distinction in DNS terminology.

RFC 1034 section 3.6 defines Resource Record Sets (RRsets) as collections of records with the same name, type, and class. For RRsets, the specification is clear about ordering:

The order of RRs in a set is not significant, and need not be preserved by name servers, resolvers, or other parts of the DNS.

However, RFC 1034 doesn’t clearly specify how message sections relate to RRsets. While modern DNS specifications have shown that message sections can indeed contain multiple RRsets (consider DNSSEC responses with signatures), RFC 1034 doesn’t describe message sections in those terms. Instead, it treats message sections as containing individual Resource Records (RRs).

The problem is that the RFC primarily discusses ordering in the context of RRsets but doesn't specify the ordering of different RRsets relative to each other within a message section. This is where the ambiguity lives.

RFC 1034 section 6.2.1 includes an example that demonstrates this ambiguity further. It mentions that the order of Resource Records (RRs) is not significant either:

The difference in ordering of the RRs in the answer section is not significant.

However, this example only shows two A records for the same name within the same RRset. It doesn't address whether this applies to different record types like CNAMEs and A records.

CNAME chain ordering

It turns out that this issue extends beyond putting CNAME records before other record types. Even when CNAMEs appear before other records, sequential parsing can still break if the CNAME chain itself is out of order. Consider the following response:

;; 

QUESTION

 SECTION

:

;; www

.

example

.

com

.

              IN

    A

;; 

ANSWER

 SECTION

:

cdn

.

example

.

com

.

           3600

  IN

    CNAME

  server

.

cdn

-

provider

.

com

.

www

.

example

.

com

.

           3600

  IN

    CNAME

  cdn

.

example

.

com

.

server

.

cdn

-

provider

.

com

.

   300

   IN

    A

      198.51

.

100.1

Each CNAME belongs to a different RRset, as they have different owners, so the statement about RRset order being insignificant doesn’t apply here.

However, RFC 1034 doesn't specify that CNAME chains must appear in any particular order. There's no requirement that www.example.com. CNAME cdn.example.com. must appear before cdn.example.com. CNAME server.cdn-provider.com.. With sequential parsing, the same issue occurs:

Find records for www.example.com

Ignore cdn.example.com. CNAME server.cdn-provider.com. as it doesn’t match the expected name

Encounter www.example.com. CNAME cdn.example.com

Find records for cdn.example.com

Ignore server.cdn-provider.com. A 198.51.100.1 as it doesn’t match the expected name

What should resolvers do?

RFC 1034 section 5 describes resolver behavior. Section 5.2.2 specifically addresses how resolvers should handle aliases (CNAMEs):

In most cases a resolver simply restarts the query at the new name when it encounters a CNAME.

This suggests that resolvers should restart the query upon finding a CNAME, regardless of where it appears in the response. However, it's important to distinguish between different types of resolvers:

Recursive resolvers, like 1.1.1.1, are full DNS resolvers that perform recursive resolution by querying authoritative nameservers

Stub resolvers, like glibc’s getaddrinfo, are simplified local interfaces that forward queries to recursive resolvers and process the responses

The RFC sections on resolver behavior were primarily written with full resolvers in mind, not the simplified stub resolvers that most applications actually use. Some stub resolvers evidently don’t implement certain parts of the spec, such as the CNAME-restart logic described in the RFC.

The DNSSEC specifications provide contrast

Later DNS specifications demonstrate a different approach to defining record ordering. RFC 4035, which defines protocol modifications for DNSSEC, uses more explicit language:

When placing a signed RRset in the Answer section, the name server MUST also place its RRSIG RRs in the Answer section. The RRSIG RRs have a higher priority for inclusion than any other RRsets that may have to be included.

The specification uses "MUST" and explicitly defines "higher priority" for RRSIG records. However, "higher priority for inclusion" refers to whether RRSIGs should be included in the response, not where they should appear. This provides unambiguous guidance to implementers about record inclusion in DNSSEC contexts, while not mandating any particular behavior around record ordering.

For unsigned zones, however, the ambiguity from RFC 1034 remains. The word "preface" has guided implementation behavior for nearly four decades, but it has never been formally specified as a requirement.

Do CNAME records come first?

While in our interpretation the RFCs do not require CNAMEs to appear in any particular order, it’s clear that at least some widely-deployed DNS clients rely on it. As some systems using these clients might be updated infrequently, or never updated at all, we believe it’s best to require CNAME records to appear in-order before any other records.

Based on what we have learned during this incident, we have reverted the CNAME re-ordering and do not intend to change the order in the future.

To prevent any future incidents or confusion, we have written a proposal in the form of an Internet-Draft to be discussed at the IETF. If consensus is reached on the clarified behavior, this would become an RFC that explicitly defines how to correctly handle CNAMEs in DNS responses, helping us and the wider DNS community navigate the protocol. The proposal can be found at https://datatracker.ietf.org/doc/draft-jabley-dnsop-ordered-answer-section. If you have suggestions or feedback we would love to hear your opinions, most usefully via the DNSOP working group at the IETF.

Related tags

1.1.1.1BugsConsumer ServicesDNSPost MortemResolverStandards

Follow on Social Media

Cloudflare

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
