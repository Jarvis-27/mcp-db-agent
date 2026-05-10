import type { Metadata } from 'next'
import Link from 'next/link'
import { PolicyPage, PolicySection } from '@/components/policy-page'

const supportEmail = 'hello@plainquery.app'

export const metadata: Metadata = {
  title: 'Terms of Service | PlainQuery',
  description:
    'PlainQuery terms covering accounts, subscriptions, acceptable use, customer data, cancellations, and refunds.',
}

export default function TermsOfServicePage() {
  return (
    <PolicyPage
      eyebrow="Terms of service"
      title="The terms for using PlainQuery."
      intro="These terms describe the rules for creating an account, connecting a database, using the hosted MCP service, and paying for a subscription."
      updated="May 10, 2026"
    >
      <PolicySection title="Agreement">
        <p>
          These Terms of Service are an agreement between PlainQuery and the
          person or organization that creates an account, accesses the service,
          or pays for a subscription. By using PlainQuery, you agree to these
          terms and to our <Link href="/privacy-policy">Privacy Policy</Link>.
        </p>
        <p>
          If you use PlainQuery for an organization, you represent that you have
          authority to bind that organization to these terms.
        </p>
      </PolicySection>

      <PolicySection title="The service">
        <p>
          PlainQuery provides digital SaaS access to a hosted MCP database agent.
          Customers connect their own database, configure an MCP client, ask a
          plain-English question, and receive generated read-only SQL and
          structured query results after validation and execution.
        </p>
        <p>
          PlainQuery is a digital service. No physical goods are sold, shipped,
          returned, or exchanged.
        </p>
      </PolicySection>

      <PolicySection title="Accounts and setup">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            You must provide accurate account, billing, and setup information
            and keep it current.
          </li>
          <li>
            You are responsible for keeping passwords, API keys, OAuth access,
            database credentials, and MCP client configuration secure.
          </li>
          <li>
            You may connect only databases and data that you are authorized to
            access and process through PlainQuery.
          </li>
          <li>
            You should use least-privilege, read-only database credentials
            whenever possible, even though PlainQuery also validates generated
            SQL as read-only.
          </li>
        </ul>
      </PolicySection>

      <PolicySection title="Subscriptions and payment">
        <p>
          PlainQuery offers free and paid plans. Current plan limits and
          features are shown in the product and on the pricing page. Paid
          subscriptions are processed by Stripe, and the applicable price,
          billing interval, taxes, and payment method are shown at checkout
          before you submit payment.
        </p>
        <p>
          By starting a paid subscription, you authorize Stripe to charge your
          selected payment method for recurring fees and applicable taxes until
          the subscription is canceled or terminated. If payment fails, we may
          reduce access, pause paid features, or move the account to the free
          plan.
        </p>
      </PolicySection>

      <PolicySection title="Cancellations, refunds, and disputes">
        <p>
          You can cancel a paid subscription from the in-app billing portal when
          available or by contacting{' '}
          <a href={`mailto:${supportEmail}`}>{supportEmail}</a>. Cancellation
          stops future renewals. Unless a refund is approved, paid plan limits
          continue through the end of the current billing period.
        </p>
        <p>
          Refunds are considered for duplicate charges, billing errors,
          unauthorized charges, accidental upgrades reported promptly, or
          service access issues caused by PlainQuery. Contact us within 30 days
          of the charge so we can investigate. Approved refunds are returned to
          the original payment method when possible.
        </p>
        <p>
          If you dispute a charge with your bank or card issuer, we may respond
          through Stripe and provide account, invoice, subscription, and service
          usage records relevant to that dispute.
        </p>
      </PolicySection>

      <PolicySection title="Customer data">
        <p>
          You retain ownership of the data, database credentials, schema,
          questions, query outputs, and other content you provide or generate
          through PlainQuery. You grant PlainQuery permission to host, transmit,
          process, secure, and display that content as needed to provide the
          service, support you, enforce these terms, and comply with law.
        </p>
        <p>
          You are responsible for the legality, accuracy, quality, and
          permissions for customer data. Do not submit data to PlainQuery if you
          do not have the right to process it through the service.
        </p>
      </PolicySection>

      <PolicySection title="Generated SQL and results">
        <p>
          PlainQuery uses automated systems and language models to generate SQL.
          The service includes safeguards such as read-only validation, table
          checks, row caps, timeouts, and retry logic, but generated SQL and
          results may still be incomplete, incorrect, or unsuitable for a
          particular decision.
        </p>
        <p>
          You are responsible for reviewing important outputs before relying on
          them. PlainQuery is not a substitute for professional, financial,
          legal, medical, compliance, or security advice.
        </p>
      </PolicySection>

      <PolicySection title="Acceptable use">
        <p>You may not use PlainQuery to:</p>
        <ul className="list-disc space-y-2 pl-5">
          <li>break the law or violate another party&apos;s rights;</li>
          <li>
            access databases, accounts, systems, or data without authorization;
          </li>
          <li>
            process data in violation of privacy, employment, export-control,
            sanctions, or sector-specific rules that apply to you;
          </li>
          <li>
            attack, probe, overload, reverse engineer, bypass limits, or disrupt
            PlainQuery or related infrastructure;
          </li>
          <li>
            upload malware, secrets you are not permitted to use, or data that
            is illegal to possess or process;
          </li>
          <li>
            resell, sublicense, or provide PlainQuery as a competing service
            without written permission.
          </li>
        </ul>
      </PolicySection>

      <PolicySection title="Service changes and termination">
        <p>
          We may update features, plan limits, integrations, and documentation
          as PlainQuery evolves. We may suspend or terminate access if we
          reasonably believe an account creates security, legal, payment,
          compliance, or operational risk, or if these terms are violated.
        </p>
        <p>
          You may stop using PlainQuery at any time. Some terms, including
          payment obligations, confidentiality, intellectual property,
          disclaimers, limits of liability, and dispute-related provisions,
          survive account termination where applicable.
        </p>
      </PolicySection>

      <PolicySection title="Intellectual property">
        <p>
          PlainQuery and its software, designs, documentation, branding, and
          service materials are owned by PlainQuery or its licensors. These
          terms do not transfer any ownership rights to you. Subject to these
          terms, you may use PlainQuery only for your own internal business or
          personal purposes.
        </p>
      </PolicySection>

      <PolicySection title="Disclaimers and limits of liability">
        <p>
          PlainQuery is provided on an &quot;as is&quot; and &quot;as available&quot; basis to the
          fullest extent permitted by law. We do not promise that the service
          will be uninterrupted, error-free, secure against every threat, or
          that every generated query or result will be correct.
        </p>
        <p>
          To the fullest extent permitted by law, PlainQuery will not be liable
          for indirect, incidental, special, consequential, exemplary, or
          punitive damages, or for lost profits, revenue, goodwill, data, or
          business opportunities. PlainQuery&apos;s total liability for claims
          relating to the service is limited to the amounts you paid to
          PlainQuery for the service in the three months before the event giving
          rise to the claim, or 100 USD if you did not pay for the service.
        </p>
      </PolicySection>

      <PolicySection title="Contact">
        <p>
          Questions about these terms, billing, cancellations, or support can be
          sent to <a href={`mailto:${supportEmail}`}>{supportEmail}</a>. You can
          also review the <Link href="/support">Support page</Link> for refund,
          dispute, cancellation, legal restriction, and promotion details.
        </p>
      </PolicySection>
    </PolicyPage>
  )
}
