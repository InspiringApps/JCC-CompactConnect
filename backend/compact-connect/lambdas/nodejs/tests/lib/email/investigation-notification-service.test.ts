import { mockClient } from 'aws-sdk-client-mock';
import 'aws-sdk-client-mock-jest';
import { Logger } from '@aws-lambda-powertools/logger';
import { SendEmailCommand, SESv2Client } from '@aws-sdk/client-sesv2';
import { S3Client } from '@aws-sdk/client-s3';
import { InvestigationNotificationService } from '../../../lib/email';
import { CompactConfigurationClient } from '../../../lib/compact-configuration-client';
import { JurisdictionClient } from '../../../lib/jurisdiction-client';
import { EmailTemplateCapture } from '../../utils/email-template-capture';
import { TReaderDocument } from '@jusdino-ia/email-builder';
import { describe, it, expect, beforeEach, beforeAll, afterAll, jest } from '@jest/globals';
import { Compact } from '../../../lib/models/compact';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';

const SAMPLE_COMPACT_CONFIG: Compact = {
    pk: 'aslp#CONFIGURATION',
    sk: 'aslp#CONFIGURATION',
    compactAdverseActionsNotificationEmails: ['adverse@example.com'],
    compactCommissionFee: {
        feeAmount: 3.5,
        feeType: 'FLAT_RATE'
    },
    compactAbbr: 'aslp',
    compactName: 'Audiology and Speech Language Pathology',
    compactOperationsTeamEmails: ['operations@example.com'],
    compactSummaryReportNotificationEmails: ['summary@example.com'],
    dateOfUpdate: '2024-12-10T19:27:28+00:00',
    type: 'compact'
};

const SAMPLE_JURISDICTION_CONFIG = {
    pk: 'aslp#CONFIGURATION',
    sk: 'aslp#JURISDICTION#oh',
    jurisdictionName: 'Ohio',
    postalAbbreviation: 'oh',
    compact: 'aslp',
    jurisdictionOperationsTeamEmails: ['oh-ops@example.com'],
    jurisdictionAdverseActionsNotificationEmails: ['oh-adverse@example.com'],
    jurisdictionSummaryReportNotificationEmails: ['oh-summary@example.com']
};

const asSESClient = (mock: ReturnType<typeof mockClient>) =>
    mock as unknown as SESv2Client;

const asS3Client = (mock: ReturnType<typeof mockClient>) =>
    mock as unknown as S3Client;

class MockCompactConfigurationClient extends CompactConfigurationClient {
    constructor() {
        super({
            logger: new Logger({ serviceName: 'test' }),
            dynamoDBClient: {} as DynamoDBClient
        });
    }

    public async getCompactConfiguration(_compact: string): Promise<Compact> {
        return SAMPLE_COMPACT_CONFIG;
    }
}

describe('InvestigationNotificationService', () => {
    let investigationService: InvestigationNotificationService;
    let mockSESClient: ReturnType<typeof mockClient>;
    let mockS3Client: ReturnType<typeof mockClient>;
    let mockCompactConfigurationClient: MockCompactConfigurationClient;
    let mockJurisdictionClient: jest.Mocked<JurisdictionClient>;

    beforeAll(() => {
        // Mock the renderTemplate method if template capture is enabled
        if (EmailTemplateCapture.isEnabled()) {
            const original = (InvestigationNotificationService.prototype as any).renderTemplate;

            jest.spyOn(InvestigationNotificationService.prototype as any, 'renderTemplate').mockImplementation(function (this: any, ...args: any[]) {
                const [template, options] = args as [TReaderDocument, any];

                EmailTemplateCapture.captureTemplate(template);
                const html = original.apply(this, args);

                EmailTemplateCapture.captureHtml(html, template, options);
                return html;
            });
        }
    });

    afterAll(() => {
        jest.restoreAllMocks();
    });

    beforeEach(() => {
        jest.clearAllMocks();
        mockSESClient = mockClient(SESv2Client);
        mockS3Client = mockClient(S3Client);
        mockCompactConfigurationClient = new MockCompactConfigurationClient();
        mockJurisdictionClient = {
            getJurisdictionConfigurations: jest.fn(),
            getJurisdictionConfiguration: jest.fn()
        } as any;

        // Reset environment variables
        process.env.FROM_ADDRESS = 'noreply@example.org';
        process.env.UI_BASE_PATH_URL = 'https://app.test.compactconnect.org';

        // Set up default successful responses
        mockSESClient.on(SendEmailCommand).resolves({
            MessageId: 'message-id-123'
        });

        mockJurisdictionClient.getJurisdictionConfiguration.mockResolvedValue(SAMPLE_JURISDICTION_CONFIG);

        investigationService = new InvestigationNotificationService({
            logger: new Logger({ serviceName: 'test' }),
            sesClient: asSESClient(mockSESClient),
            s3Client: asS3Client(mockS3Client),
            compactConfigurationClient: mockCompactConfigurationClient,
            jurisdictionClient: mockJurisdictionClient
        });
    });

    describe('License Investigation Provider Notification', () => {
        it('should send license investigation provider notification email', async () => {
            await investigationService.sendLicenseInvestigationProviderNotificationEmail(
                'aslp',
                ['provider@example.com'],
                'John',
                'Doe',
                'OH',
                'Audiologist'
            );

            expect(mockSESClient).toHaveReceivedCommandWith(SendEmailCommand, {
                Destination: {
                    ToAddresses: ['provider@example.com']
                },
                Content: {
                    Simple: {
                        Body: {
                            Html: {
                                Charset: 'UTF-8',
                                Data: expect.stringContaining('Your Audiologist license in Ohio is under investigation')
                            }
                        },
                        Subject: {
                            Charset: 'UTF-8',
                            Data: 'Your Audiologist license in Ohio is under investigation'
                        }
                    }
                },
                FromEmailAddress: 'Compact Connect <noreply@example.org>'
            });
        });

        it('should throw error when no recipients provided', async () => {
            await expect(
                investigationService.sendLicenseInvestigationProviderNotificationEmail(
                    'aslp',
                    [],
                    'John',
                    'Doe',
                    'OH',
                    'Audiologist'
                )
            ).rejects.toThrow('No recipients specified for provider license investigation notification email');
        });
    });

    describe('License Investigation State Notification', () => {
        it('should send license investigation state notification email', async () => {
            await investigationService.sendLicenseInvestigationStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH',
                'Audiologist'
            );

            expect(mockSESClient).toHaveReceivedCommandWith(SendEmailCommand, {
                Destination: {
                    ToAddresses: ['oh-adverse@example.com']
                },
                Content: {
                    Simple: {
                        Body: {
                            Html: {
                                Charset: 'UTF-8',
                                Data: expect.stringContaining('John Doe holding Audiologist license in Ohio is under investigation')
                            }
                        },
                        Subject: {
                            Charset: 'UTF-8',
                            Data: 'John Doe holding Audiologist license in Ohio is under investigation'
                        }
                    }
                },
                FromEmailAddress: 'Compact Connect <noreply@example.org>'
            });
        });

        it('should handle missing jurisdiction configuration gracefully', async () => {
            mockJurisdictionClient.getJurisdictionConfiguration.mockRejectedValue(new Error('Jurisdiction not found'));

            await investigationService.sendLicenseInvestigationStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH',
                'Audiologist'
            );

            // Should not throw an error, but also should not send email
            expect(mockSESClient).not.toHaveReceivedCommand(SendEmailCommand);
        });
    });

    describe('License Investigation Closed Provider Notification', () => {
        it('should send license investigation closed provider notification email', async () => {
            await investigationService.sendLicenseInvestigationClosedProviderNotificationEmail(
                'aslp',
                ['provider@example.com'],
                'John',
                'Doe',
                'OH',
                'Audiologist'
            );

            expect(mockSESClient).toHaveReceivedCommandWith(SendEmailCommand, {
                Destination: {
                    ToAddresses: ['provider@example.com']
                },
                Content: {
                    Simple: {
                        Body: {
                            Html: {
                                Charset: 'UTF-8',
                                Data: expect.stringContaining('The investigation on your Audiologist license in Ohio has been closed')
                            }
                        },
                        Subject: {
                            Charset: 'UTF-8',
                            Data: 'The investigation on your Audiologist license in Ohio has been closed'
                        }
                    }
                },
                FromEmailAddress: 'Compact Connect <noreply@example.org>'
            });
        });

        it('should throw error when no recipients provided', async () => {
            await expect(
                investigationService.sendLicenseInvestigationClosedProviderNotificationEmail(
                    'aslp',
                    [],
                    'John',
                    'Doe',
                    'OH',
                    'Audiologist'
                )
            ).rejects.toThrow('No recipients specified for provider license investigation closed notification email');
        });
    });

    describe('License Investigation Closed State Notification', () => {
        it('should send license investigation closed state notification email', async () => {
            await investigationService.sendLicenseInvestigationClosedStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH',
                'Audiologist'
            );

            expect(mockSESClient).toHaveReceivedCommandWith(SendEmailCommand, {
                Destination: {
                    ToAddresses: ['oh-adverse@example.com']
                },
                Content: {
                    Simple: {
                        Body: {
                            Html: {
                                Charset: 'UTF-8',
                                Data: expect.stringContaining('holding a <em>Audiologist</em> license in Ohio has been closed')
                            }
                        },
                        Subject: {
                            Charset: 'UTF-8',
                            Data: 'Investigation on John Doe\'s Audiologist license in Ohio has been closed'
                        }
                    }
                },
                FromEmailAddress: 'Compact Connect <noreply@example.org>'
            });
        });
    });

    describe('Privilege Investigation Provider Notification', () => {
        it('should send privilege investigation provider notification email', async () => {
            await investigationService.sendPrivilegeInvestigationProviderNotificationEmail(
                'aslp',
                ['provider@example.com'],
                'John',
                'Doe',
                'OH',
                'Audiologist'
            );

            expect(mockSESClient).toHaveReceivedCommandWith(SendEmailCommand, {
                Destination: {
                    ToAddresses: ['provider@example.com']
                },
                Content: {
                    Simple: {
                        Body: {
                            Html: {
                                Charset: 'UTF-8',
                                Data: expect.stringContaining('Your Audiologist privilege in Ohio is under investigation')
                            }
                        },
                        Subject: {
                            Charset: 'UTF-8',
                            Data: 'Your Audiologist privilege in Ohio is under investigation'
                        }
                    }
                },
                FromEmailAddress: 'Compact Connect <noreply@example.org>'
            });
        });

        it('should throw error when no recipients provided', async () => {
            await expect(
                investigationService.sendPrivilegeInvestigationProviderNotificationEmail(
                    'aslp',
                    [],
                    'John',
                    'Doe',
                    'OH',
                    'Audiologist'
                )
            ).rejects.toThrow('No recipients specified for provider privilege investigation notification email');
        });
    });

    describe('Privilege Investigation State Notification', () => {
        it('should send privilege investigation state notification email', async () => {
            await investigationService.sendPrivilegeInvestigationStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH',
                'Audiologist'
            );

            expect(mockSESClient).toHaveReceivedCommandWith(SendEmailCommand, {
                Destination: {
                    ToAddresses: ['oh-adverse@example.com']
                },
                Content: {
                    Simple: {
                        Body: {
                            Html: {
                                Charset: 'UTF-8',
                                Data: expect.stringContaining('John Doe holding Audiologist privilege in Ohio is under investigation')
                            }
                        },
                        Subject: {
                            Charset: 'UTF-8',
                            Data: 'John Doe holding Audiologist privilege in Ohio is under investigation'
                        }
                    }
                },
                FromEmailAddress: 'Compact Connect <noreply@example.org>'
            });
        });
    });

    describe('Privilege Investigation Closed Provider Notification', () => {
        it('should send privilege investigation closed provider notification email', async () => {
            await investigationService.sendPrivilegeInvestigationClosedProviderNotificationEmail(
                'aslp',
                ['provider@example.com'],
                'John',
                'Doe',
                'OH',
                'Audiologist'
            );

            expect(mockSESClient).toHaveReceivedCommandWith(SendEmailCommand, {
                Destination: {
                    ToAddresses: ['provider@example.com']
                },
                Content: {
                    Simple: {
                        Body: {
                            Html: {
                                Charset: 'UTF-8',
                                Data: expect.stringContaining('The investigation on your Audiologist privilege in Ohio has been closed')
                            }
                        },
                        Subject: {
                            Charset: 'UTF-8',
                            Data: 'The investigation on your Audiologist privilege in Ohio has been closed'
                        }
                    }
                },
                FromEmailAddress: 'Compact Connect <noreply@example.org>'
            });
        });

        it('should throw error when no recipients provided', async () => {
            await expect(
                investigationService.sendPrivilegeInvestigationClosedProviderNotificationEmail(
                    'aslp',
                    [],
                    'John',
                    'Doe',
                    'OH',
                    'Audiologist'
                )
            ).rejects.toThrow('No recipients specified for provider privilege investigation closed notification email');
        });
    });

    describe('Privilege Investigation Closed State Notification', () => {
        it('should send privilege investigation closed state notification email', async () => {
            await investigationService.sendPrivilegeInvestigationClosedStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH',
                'Audiologist'
            );

            expect(mockSESClient).toHaveReceivedCommandWith(SendEmailCommand, {
                Destination: {
                    ToAddresses: ['oh-adverse@example.com']
                },
                Content: {
                    Simple: {
                        Body: {
                            Html: {
                                Charset: 'UTF-8',
                                Data: expect.stringContaining('holding a <em>Audiologist</em> privilege in Ohio has been closed')
                            }
                        },
                        Subject: {
                            Charset: 'UTF-8',
                            Data: 'Investigation on John Doe\'s Audiologist privilege in Ohio has been closed'
                        }
                    }
                },
                FromEmailAddress: 'Compact Connect <noreply@example.org>'
            });
        });
    });

    describe('Error Handling', () => {
        it('should handle SES client errors gracefully', async () => {
            mockSESClient.on(SendEmailCommand).rejects(new Error('SES service error'));

            await expect(
                investigationService.sendLicenseInvestigationProviderNotificationEmail(
                    'aslp',
                    ['provider@example.com'],
                    'John',
                    'Doe',
                    'OH',
                    'Audiologist'
                )
            ).rejects.toThrow('SES service error');
        });

        it('should handle missing adverse action recipients gracefully', async () => {
            const jurisdictionConfigWithoutAdverseActions = {
                ...SAMPLE_JURISDICTION_CONFIG,
                jurisdictionAdverseActionsNotificationEmails: []
            };

            mockJurisdictionClient.getJurisdictionConfiguration.mockResolvedValue(
                jurisdictionConfigWithoutAdverseActions
            );

            await investigationService.sendLicenseInvestigationStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH',
                'Audiologist'
            );

            // Should not throw an error, but also should not send email
            expect(mockSESClient).not.toHaveReceivedCommand(SendEmailCommand);
        });

        it('should handle missing recipients for license investigation closed state notification', async () => {
            const jurisdictionConfigWithoutAdverseActions = {
                ...SAMPLE_JURISDICTION_CONFIG,
                jurisdictionAdverseActionsNotificationEmails: []
            };

            mockJurisdictionClient.getJurisdictionConfiguration.mockResolvedValue(
                jurisdictionConfigWithoutAdverseActions
            );

            await investigationService.sendLicenseInvestigationClosedStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH',
                'Audiologist'
            );

            // Should not throw an error, but also should not send email
            expect(mockSESClient).not.toHaveReceivedCommand(SendEmailCommand);
        });

        it('should handle missing recipients for privilege investigation state notification', async () => {
            const jurisdictionConfigWithoutAdverseActions = {
                ...SAMPLE_JURISDICTION_CONFIG,
                jurisdictionAdverseActionsNotificationEmails: []
            };

            mockJurisdictionClient.getJurisdictionConfiguration.mockResolvedValue(
                jurisdictionConfigWithoutAdverseActions
            );

            await investigationService.sendPrivilegeInvestigationStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH',
                'Audiologist'
            );

            // Should not throw an error, but also should not send email
            expect(mockSESClient).not.toHaveReceivedCommand(SendEmailCommand);
        });

        it('should handle missing recipients for privilege investigation closed state notification', async () => {
            const jurisdictionConfigWithoutAdverseActions = {
                ...SAMPLE_JURISDICTION_CONFIG,
                jurisdictionAdverseActionsNotificationEmails: []
            };

            mockJurisdictionClient.getJurisdictionConfiguration.mockResolvedValue(
                jurisdictionConfigWithoutAdverseActions
            );

            await investigationService.sendPrivilegeInvestigationClosedStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH',
                'Audiologist'
            );

            // Should not throw an error, but also should not send email
            expect(mockSESClient).not.toHaveReceivedCommand(SendEmailCommand);
        });

        it('should handle same notifying and affected jurisdiction', async () => {
            // Reset mocks to ensure clean state
            jest.clearAllMocks();
            mockJurisdictionClient.getJurisdictionConfiguration.mockResolvedValue(SAMPLE_JURISDICTION_CONFIG);

            // When notifying jurisdiction equals affected jurisdiction, it should use the same config
            await investigationService.sendLicenseInvestigationStateNotificationEmail(
                'aslp',
                'OH',
                'John',
                'Doe',
                'provider-123',
                'OH', // Same as notifying jurisdiction
                'Audiologist'
            );

            // Should have been called at least once with the jurisdiction
            expect(mockJurisdictionClient.getJurisdictionConfiguration).toHaveBeenCalledWith('aslp', 'OH');
            // Should have sent the email successfully
            expect(mockSESClient).toHaveReceivedCommand(SendEmailCommand);
        });
    });
});
