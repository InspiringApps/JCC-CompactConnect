import * as fs from 'fs';
import * as path from 'path';
import { TReaderDocument, renderToStaticMarkup as realRenderToStaticMarkup } from '@jusdino-ia/email-builder';

/**
 * Utility for capturing email templates during testing
 * This can be toggled on/off via environment variable CAPTURE_EMAIL_TEMPLATES
 */
export class EmailTemplateCapture {
    private static outputDir: string;

    /**
     * Check if template capture is enabled via environment variable
     */
    static isEnabled(): boolean {
        return process.env.CAPTURE_EMAIL_TEMPLATES === 'true';
    }

    /**
     * Get the current test name from Jest's test context
     */
    private static getCurrentTestName(): string {
        // Get the current test name from Jest's expect context
        const expect = (global as any).expect;

        if (expect && expect.getState) {
            const state = expect.getState();

            if (state && state.currentTestName) {
                return state.currentTestName;
            }
        }

        return 'unknown-test';
    }

    /**
     * Generate a sanitized filename based on the current test name
     */
    private static generateFilename(extension: string): string {
        const testName = this.getCurrentTestName();

        // Extract the most meaningful part of the test name
        // For patterns like "CognitoEmailService generateCognitoMessage should generate SignUp message"
        // We want to prioritize the part after "should"
        let meaningfulPart = testName;

        // Try to extract the part after the last "should"
        const shouldIndex = testName.lastIndexOf(' should ');

        if (shouldIndex !== -1) {
            meaningfulPart = testName.substring(shouldIndex + 8); // +8 for " should "
        }

        // If that's still too generic, try to get the last part after the last space
        if (meaningfulPart.length < 10) {
            const lastSpaceIndex = testName.lastIndexOf(' ');

            if (lastSpaceIndex !== -1) {
                meaningfulPart = testName.substring(lastSpaceIndex + 1);
            }
        }

        // Sanitize test name for filename (remove special characters, spaces, etc.)
        const sanitizedTestName = meaningfulPart
            .replace(/[^a-zA-Z0-9\s-]/g, '') // Remove special characters except spaces and hyphens
            .replace(/\s+/g, '-') // Replace spaces with hyphens
            .toLowerCase()
            .substring(0, 80); // Increased limit to 80 characters

        return `${sanitizedTestName}.${extension}`;
    }

    /**
     * Ensure the output directory exists and return its path
     */
    private static ensureOutputDirectory(): string {
        if (!this.outputDir) {
            this.outputDir = path.join(__dirname, '..', '..', 'generated-email-templates');
            console.log('📧 Email template capture is ENABLED');
        }

        // Ensure the directory exists
        fs.mkdirSync(this.outputDir, { recursive: true });

        return this.outputDir;
    }

    /**
     * Capture a template if capture is enabled
     */
    static captureTemplate(template: TReaderDocument) {
        if (!this.isEnabled()) {
            return;
        }

        const outputDir = this.ensureOutputDirectory();
        const filename = this.generateFilename('json');
        const filepath = path.join(outputDir, filename);

        // Create template data with metadata
        const templateData = {
            metadata: {
                testName: this.getCurrentTestName(),
                generatedAt: new Date().toISOString(),
                rootBlockId: 'root'
            },
            // This is the raw TReaderDocument that can be used with EmailBuilderJS
            emailBuilderTemplate: template
        };

        // Write to file
        fs.writeFileSync(filepath, JSON.stringify(templateData, null, 2));
        console.log(`📧 Captured email template: ${filename}`);
    }

    /**
     * Mock implementation of renderTemplate that captures templates and calls the real renderToStaticMarkup
     * This should be used in tests to mock the BaseEmailService.renderTemplate method
     */
    static mockRenderTemplate(...args: unknown[]): string {
        const template = args[0] as TReaderDocument;

        // Capture the template if enabled
        EmailTemplateCapture.captureTemplate(template);

        // Always call the real renderToStaticMarkup function to get actual HTML
        const html = realRenderToStaticMarkup(template, { rootBlockId: 'root' });

        // Also capture the rendered HTML if enabled
        if (EmailTemplateCapture.isEnabled()) {
            EmailTemplateCapture.captureHtml(html, template);
        }

        return html;
    }

    /**
     * Capture the rendered HTML output for debugging
     */
    static captureHtml(html: string, template: TReaderDocument) {
        if (!this.isEnabled()) {
            return;
        }

        const outputDir = this.ensureOutputDirectory();
        const filename = this.generateFilename('html');
        const filepath = path.join(outputDir, filename);

        // Create HTML data with metadata
        const htmlData = {
            metadata: {
                testName: this.getCurrentTestName(),
                generatedAt: new Date().toISOString(),
                rootBlockId: 'root',
                note: 'This is the final rendered HTML output from EmailBuilderJS'
            },
            html: html
        };

        // Write to file
        fs.writeFileSync(filepath, JSON.stringify(htmlData, null, 2));
        console.log(`📧 Captured rendered HTML: ${filename}`);
    }
}
