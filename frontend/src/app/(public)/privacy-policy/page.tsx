import type { Metadata } from 'next'
import Link from 'next/link'
import { PolicyPage, PolicySection } from '@/components/policy-page'

const supportEmail = 'hello@plainquery.in'

export const metadata: Metadata = {
  title: 'Privacy Policy | PlainQuery',
  description:
    'How PlainQuery collects, uses, shares, protects, and retains customer data.',
  alternates: {
    canonical: '/privacy-policy',
  },
}

export default function PrivacyPolicyPage() {
  return (
    <PolicyPage
      eyebrow="Privacy policy"
      title="How PlainQuery handles customer data."
      intro="This policy explains what we collect, why we collect it, and the choices available to PlainQuery account holders and visitors."
      updated="May 10, 2026"
    >
      <PolicySection title="Scope">
        <p>
          This Privacy Policy applies to PlainQuery websites, hosted
          application pages, support communications, and billing flows. It does
          not apply to third-party products you connect to PlainQuery, such as
          your database provider, MCP client, Stripe, or a configured language
          model provider.
        </p>
        <p>
          PlainQuery acts as a service provider for the data customers submit to
          use the service. Customers are responsible for having the rights and
          notices needed to connect their databases and ask questions about the
          data they control.
        </p>
      </PolicySection>

      <PolicySection title="Information we collect">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong>Account information:</strong> email address, login or
            verification details, account status, onboarding status, plan, and
            support preferences.
          </li>
          <li>
            <strong>Service configuration:</strong> database connection URLs,
            selected LLM provider, LLM API keys when supplied by the customer,
            MCP setup choices, API key metadata, and related settings.
            Sensitive credentials are encrypted at rest.
          </li>
          <li>
            <strong>Query history and usage:</strong> plain-English questions,
            generated SQL, success or failure status, row counts, timings,
            errors, quota metadata, API key identifiers, and timestamps. The
            persistent query history stores metadata and generated SQL, not full
            result rows.
          </li>
          <li>
            <strong>Payment information:</strong> Stripe customer IDs,
            subscription IDs, price IDs, billing status, invoice or receipt
            references, and webhook event records. PlainQuery does not receive
            full card numbers from Stripe.
          </li>
          <li>
            <strong>Support and operations data:</strong> messages you send us,
            diagnostic information, IP address, browser or device information,
            logs, security events, and service availability data.
          </li>
        </ul>
      </PolicySection>

      <PolicySection title="How we use information">
        <ul className="list-disc space-y-2 pl-5">
          <li>Provide, secure, monitor, and improve PlainQuery.</li>
          <li>Create accounts, verify access, and manage API keys.</li>
          <li>
            Generate, validate, execute, and troubleshoot read-only SQL queries.
          </li>
          <li>Apply plan limits, quotas, billing status, and entitlements.</li>
          <li>Process subscriptions, cancellations, refunds, and disputes.</li>
          <li>Respond to support, security, legal, and compliance requests.</li>
          <li>
            Send service notices, account emails, billing emails, and limited
            product communications where allowed.
          </li>
        </ul>
      </PolicySection>

      <PolicySection title="LLM providers and payment processors">
        <p>
          To generate SQL, PlainQuery may send your question, database schema
          context, generated SQL, validation errors, and execution errors to the
          language model provider configured for your account, such as Anthropic
          or Groq. PlainQuery does not sell customer data or use customer
          database contents to train PlainQuery-owned models.
        </p>
        <p>
          Payments are processed by Stripe. Stripe handles payment method data
          under its own terms and privacy practices. You can review Stripe&apos;s
          privacy information at{' '}
          <a
            href="https://stripe.com/privacy"
            target="_blank"
            rel="noopener noreferrer"
          >
            stripe.com/privacy
          </a>
          .
        </p>
      </PolicySection>

      <PolicySection title="How we share information">
        <p>
          We share information only as needed to run PlainQuery, comply with the
          law, protect customers, or complete actions you request. This may
          include sharing with hosting, database, email, logging, security,
          customer support, payment, and LLM service providers.
        </p>
        <p>
          We may also share information with professional advisers, authorities,
          or counterparties in connection with legal obligations, safety,
          fraud-prevention, disputes, enforcement of our terms, or a merger,
          acquisition, financing, or sale of assets.
        </p>
      </PolicySection>

      <PolicySection title="Security and retention">
        <p>
          PlainQuery uses technical and organizational safeguards designed to
          protect customer data, including credential encryption at rest,
          database URL validation, request scoping, rate limits, query row caps,
          execution timeouts, and audit records. No internet service can be made
          perfectly secure, so customers should use least-privilege database
          credentials and keep API keys confidential.
        </p>
        <p>
          We retain information for as long as needed to provide the service,
          meet legal and accounting requirements, resolve disputes, enforce
          agreements, and maintain security. When information is no longer
          needed, we delete it or de-identify it where practical.
        </p>
      </PolicySection>

      <PolicySection title="Your choices">
        <p>
          You can update account details, rotate API keys, change database
          configuration, cancel paid subscriptions, or request account deletion
          through the product where available or by contacting{' '}
          <a href={`mailto:${supportEmail}`}>{supportEmail}</a>.
        </p>
        <p>
          Depending on where you live, you may have rights to access, correct,
          delete, export, restrict, or object to certain processing of your
          personal information. We may need to verify your request before acting
          on it.
        </p>
      </PolicySection>

      <PolicySection title="Children">
        <p>
          PlainQuery is not directed to children under 13, and we do not
          knowingly collect personal information from children under 13.
        </p>
      </PolicySection>

      <PolicySection title="Changes and contact">
        <p>
          We may update this Privacy Policy as PlainQuery changes. The updated
          version will be posted on this page with a new last updated date.
        </p>
        <p>
          Privacy questions can be sent to{' '}
          <a href={`mailto:${supportEmail}`}>{supportEmail}</a>. You can also
          review our <Link href="/support">Support page</Link> and{' '}
          <Link href="/terms-of-service">Terms of Service</Link>.
        </p>
      </PolicySection>
    </PolicyPage>
  )
}
