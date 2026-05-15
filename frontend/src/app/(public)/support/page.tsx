import type { Metadata } from 'next'
import Link from 'next/link'
import { PolicyPage, PolicySection } from '@/components/policy-page'

const supportEmail = 'support@plainquery.in'

export const metadata: Metadata = {
  title: 'Support | PlainQuery',
  description:
    'Support, billing, cancellation, refund, and product information for PlainQuery customers.',
}

export default function SupportPage() {
  return (
    <PolicyPage
      eyebrow="Support"
      title="Support and billing help for PlainQuery."
      intro="PlainQuery provides subscription access to a hosted MCP database agent for asking read-only database questions in plain English."
      updated="May 10, 2026"
    >
      <PolicySection title="Business and service">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong>Business name:</strong> PlainQuery.
          </li>
          <li>
            <strong>Website:</strong>{' '}
            <a href="https://plainquery.in">https://plainquery.in</a>.
          </li>
          <li>
            <strong>Service offered:</strong> digital SaaS access to an MCP
            server that connects to customer-provided PostgreSQL or SQLite
            databases, generates read-only SQL from plain-English
            questions, validates that SQL, and returns structured query results.
          </li>
          <li>
            <strong>Delivery:</strong> account access is delivered online after
            signup and setup. PlainQuery does not sell or ship physical goods.
          </li>
        </ul>
      </PolicySection>

      <PolicySection title="Contact support">
        <ul className="list-disc space-y-2 pl-5">
          <li>
            <strong>Email:</strong>{' '}
            <a href={`mailto:${supportEmail}`}>{supportEmail}</a>
          </li>
          <li>
            <strong>Phone:</strong>{' '}
            <a href="tel:+917015854119">+91 7015854119</a>
          </li>
          <li>
            <strong>Address:</strong> #919, Dwarkapuri, Jagadhri, Haryana –
            135003, District Yamunanagar, India
          </li>
        </ul>
        <p>
          Include the email address on your PlainQuery account, a short
          description of the issue, relevant timestamps, and any Stripe receipt
          or invoice ID for billing questions.
        </p>
        <p>
          We review support requests on business days and prioritize account
          access, billing, security, and service availability issues first.
        </p>
      </PolicySection>

      <PolicySection title="Billing, refunds, and disputes">
        <p>
          Paid subscriptions are processed by Stripe. The price, renewal period,
          taxes, and payment method are shown at checkout before payment is
          submitted. Stripe may also email receipts and payment updates.
        </p>
        <p>
          If you believe a charge is incorrect, duplicate, unauthorized, or
          connected to a service access problem caused by PlainQuery, contact us
          within 30 days at{' '}
          <a href={`mailto:${supportEmail}`}>{supportEmail}</a>. Approved
          refunds are returned to the original payment method when possible.
          Card and bank processing times are controlled by the payment networks
          and financial institutions involved.
        </p>
        <p>
          We try to resolve billing issues directly before they become payment
          disputes. If a dispute is filed with a bank or card issuer, we respond
          through Stripe and may need to provide account, invoice, and service
          usage records related to the disputed charge.
        </p>
      </PolicySection>

      <PolicySection title="Cancellations">
        <p>
          You can cancel a paid subscription from the in-app billing portal when
          it is available for your account, or by emailing{' '}
          <a href={`mailto:${supportEmail}`}>{supportEmail}</a>. Cancellation
          stops future renewals. Unless a refund is approved, access to paid
          plan limits continues until the end of the current billing period and
          the account then returns to the free plan.
        </p>
      </PolicySection>

      <PolicySection title="Legal, export, and promotion terms">
        <p>
          PlainQuery may only be used with databases and data you are authorized
          to access. You may not use the service where prohibited by law,
          sanctions, export-control rules, or applicable third-party terms.
        </p>
        <p>
          Any promotion, trial, credit, or discount is subject to the specific
          terms shown with that offer. Promotions are not transferable, may have
          expiration dates, and may be limited to one per customer unless the
          offer says otherwise.
        </p>
      </PolicySection>

      <PolicySection title="Related policies">
        <p>
          Review the{' '}
          <Link href="/privacy-policy">PlainQuery Privacy Policy</Link> and{' '}
          <Link href="/terms-of-service">PlainQuery Terms of Service</Link> for
          more detail on data handling, account rules, subscriptions, and
          acceptable use.
        </p>
      </PolicySection>
    </PolicyPage>
  )
}
